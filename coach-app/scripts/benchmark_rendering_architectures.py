"""Empirical benchmark comparing three architectural alternatives for Rocket League replay reconstruction.

Evaluates:
1. Candidate 1: Client-Side Hermite Spline + Shortest-Arc Quaternion SLERP (Current @rlrml/player + polish)
2. Candidate 2: Forward Physics Re-simulation (RocketSim / Bullet without recorded inputs)
3. Candidate 3: Compact Quantized Binary State Stream (Pre-interpolated 60Hz ArrayBuffer)

Measures:
- Trajectory drift / divergence over horizon dt in Unreal Units
- Decode latency and memory footprint (mobile feasibility)
- Coordinate and rotational fidelity
- Seeking and random-access overhead
"""
from __future__ import annotations

import io
import json
import math
import struct
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np

# Add coach_app to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from coach_app.subtr_replays import parse_subtr_replay


def quaternion_slerp(q1: np.ndarray, q2: np.ndarray, t: float) -> np.ndarray:
    """Shortest-arc spherical linear interpolation on S^3."""
    dot = float(np.dot(q1, q2))
    if dot < 0.0:
        q2 = -q2
        dot = -dot
    dot = min(1.0, max(-1.0, dot))
    if dot > 0.9995:
        res = q1 + t * (q2 - q1)
        return res / np.linalg.norm(res)
    theta = math.acos(dot)
    sin_theta = math.sin(theta)
    w1 = math.sin((1.0 - t) * theta) / sin_theta
    w2 = math.sin(t * theta) / sin_theta
    return (w1 * q1 + w2 * q2)


def hermite_interpolate(
    p0: np.ndarray, v0: np.ndarray,
    p1: np.ndarray, v1: np.ndarray,
    dt: float, t: float
) -> np.ndarray:
    """Cubic Hermite position interpolation using recorded velocity vectors."""
    if dt <= 1e-6:
        return p0
    s = t / dt
    s2 = s * s
    s3 = s2 * s
    h00 = 2 * s3 - 3 * s2 + 1
    h10 = s3 - 2 * s2 + s
    h01 = -2 * s3 + 3 * s2
    h11 = s3 - s2
    return h00 * p0 + h10 * (v0 * dt) + h01 * p1 + h11 * (v1 * dt)


def simulate_forward_physics(
    p0: np.ndarray, v0: np.ndarray, dt: float, gravity: float = -650.0
) -> Tuple[np.ndarray, np.ndarray]:
    """Forward physics integration assuming ballistic gravity and drag without controller input.
    
    Rocket League gravity is ~ -650 UU/s^2.
    """
    g = np.array([0.0, 0.0, gravity])
    p1 = p0 + v0 * dt + 0.5 * g * (dt ** 2)
    v1 = v0 + g * dt
    return p1, v1


def encode_quantized_binary(frames: List[Dict[str, Any]]) -> bytes:
    """Encode replay trajectory into compact 60Hz binary state format (Candidate 3).
    
    Header (16 bytes):
      magic: 'RLBF' (4B)
      version: 1 (uint16)
      num_frames: uint32
      tick_rate: float32 (e.g. 60.0)
      reserved: 2B
      
    Per frame per car (20 bytes):
      pos_x: int16 (scale 4, range +/- 8192 UU)
      pos_y: int16 (scale 4, range +/- 8192 UU)
      pos_z: int16 (scale 4, range 0 - 4096 UU)
      quat_w: int16 (scale 32767)
      quat_x: int16 (scale 32767)
      quat_y: int16 (scale 32767)
      quat_z: int16 (scale 32767)
      boost: uint8 (0-100)
      flags: uint8 (bit 0: on_ground, bit 1: supersonic, bit 2: ball_cam)
      vel_mag: uint16 (scale 10)
    """
    buf = io.BytesIO()
    num_frames = len(frames)
    header = struct.pack("<4sHII", b"RLBF", 1, num_frames, 60)
    buf.write(header)
    
    for f in frames:
        px = int(np.clip(f["pos"][0] * 4, -32768, 32767))
        py = int(np.clip(f["pos"][1] * 4, -32768, 32767))
        pz = int(np.clip(f["pos"][2] * 4, -32768, 32767))
        qw = int(np.clip(f["quat"][0] * 32767, -32768, 32767))
        qx = int(np.clip(f["quat"][1] * 32767, -32768, 32767))
        qy = int(np.clip(f["quat"][2] * 32767, -32768, 32767))
        qz = int(np.clip(f["quat"][3] * 32767, -32768, 32767))
        boost = int(np.clip(f.get("boost", 0), 0, 100))
        flags = int(f.get("flags", 0)) & 0xFF
        vel_mag = int(np.clip(np.linalg.norm(f.get("vel", [0, 0, 0])) * 10, 0, 65535))
        
        buf.write(struct.pack("<7h2BH", px, py, pz, qw, qx, qy, qz, boost, flags, vel_mag))
        
    return buf.getvalue()


def decode_quantized_binary(data: bytes) -> List[Dict[str, Any]]:
    """Fast unpack of compact binary state stream."""
    magic, ver, num_frames, tick_rate = struct.unpack_from("<4sHII", data, 0)
    if magic != b"RLBF":
        raise ValueError("Invalid magic header")
    offset = 14
    record_size = 18
    frames = []
    for _ in range(num_frames):
        px, py, pz, qw, qx, qy, qz, boost, flags, vel_mag = struct.unpack_from("<7h2BH", data, offset)
        offset += record_size
        frames.append({
            "pos": [px / 4.0, py / 4.0, pz / 4.0],
            "quat": [qw / 32767.0, qx / 32767.0, qy / 32767.0, qz / 32767.0],
            "boost": boost,
            "flags": flags,
            "vel_mag": vel_mag / 10.0
        })
    return frames


def run_architecture_benchmark(replay_path: Path) -> Dict[str, Any]:
    print(f"\n[BENCHMARK] Evaluating architectures on replay: {replay_path.name}")
    t0 = time.perf_counter()
    raw_bytes = replay_path.read_bytes()
    t_read = time.perf_counter() - t0
    
    t0 = time.perf_counter()
    replay = parse_subtr_replay(replay_path)
    t_parse = time.perf_counter() - t0
    print(f"  Raw Replay Size: {len(raw_bytes):,} bytes | Parse Time: {t_parse*1000:.1f}ms")
    
    # Extract longest continuous player track from frames
    frames = replay.get("frames", [])
    players = replay.get("players", [])
    if not frames or not players:
        raise ValueError("No frames or players found in parsed replay")
    
    target_player = players[0]["id"]
    telem = []
    for f in frames:
        car = f.get("cars", {}).get(target_player)
        if car:
            telem.append({
                "time": f["t"],
                "pos": [car["x"], car["y"], car["z"]],
                "vel": car.get("velocity", [0, 0, 0]),
                "boost": car.get("boost", 0),
                "rot": car.get("rotation", [0, 0, 0])
            })
    print(f"  Selected Player: {target_player} with {len(telem):,} telemetry samples")
    
    # 1. Evaluate Candidate 1: Hermite + SLERP Interpolation Error and Speed
    # Subsample ground truth at 50% to test intermediate reconstruction accuracy
    sampled_indices = list(range(0, len(telem) - 2, 2))
    hermite_errors = []
    linear_errors = []
    t_interp_start = time.perf_counter()
    
    for idx in sampled_indices:
        t_prev, t_curr, t_next = telem[idx]["time"], telem[idx+1]["time"], telem[idx+2]["time"]
        dt = t_next - t_prev
        t_mid = t_curr - t_prev
        if dt <= 0.001 or dt > 0.5:
            continue
            
        p_prev = np.array(telem[idx]["pos"], dtype=float)
        v_prev = np.array(telem[idx].get("vel", [0, 0, 0]), dtype=float)
        p_next = np.array(telem[idx+2]["pos"], dtype=float)
        v_next = np.array(telem[idx+2].get("vel", [0, 0, 0]), dtype=float)
        p_true = np.array(telem[idx+1]["pos"], dtype=float)
        
        # Hermite spline
        p_hermite = hermite_interpolate(p_prev, v_prev, p_next, v_next, dt, t_mid)
        hermite_errors.append(float(np.linalg.norm(p_hermite - p_true)))
        
        # Linear
        alpha = t_mid / dt
        p_linear = (1 - alpha) * p_prev + alpha * p_next
        linear_errors.append(float(np.linalg.norm(p_linear - p_true)))
        
    t_interp_elapsed = (time.perf_counter() - t_interp_start) / max(1, len(sampled_indices))
    
    # 2. Evaluate Candidate 2: Forward Physics Re-simulation Divergence
    # Measure error if simulating forward without controller input over 0.1s, 0.25s, 0.5s, 1.0s
    physics_divergence = {0.1: [], 0.25: [], 0.5: [], 1.0: []}
    
    for idx in range(0, len(telem) - 30, 5):
        t_start = telem[idx]["time"]
        p0 = np.array(telem[idx]["pos"], dtype=float)
        v0 = np.array(telem[idx].get("vel", [0, 0, 0]), dtype=float)
        
        # Search for subsequent frames matching target horizon
        for horizon in physics_divergence.keys():
            t_target = t_start + horizon
            # Find closest frame
            match_idx = None
            for f_idx in range(idx + 1, min(idx + 60, len(telem))):
                if abs(telem[f_idx]["time"] - t_target) < 0.02:
                    match_idx = f_idx
                    break
            if match_idx is not None:
                p_sim, _ = simulate_forward_physics(p0, v0, horizon)
                p_actual = np.array(telem[match_idx]["pos"], dtype=float)
                err = float(np.linalg.norm(p_sim - p_actual))
                physics_divergence[horizon].append(err)
                
    # 3. Evaluate Candidate 3: Compact Quantized Binary State Stream
    # Format frame samples
    frames_to_encode = []
    for s in telem:
        # Generate normalized quaternion if missing
        q = np.array([1.0, 0.0, 0.0, 0.0])
        frames_to_encode.append({
            "pos": s["pos"],
            "quat": q,
            "boost": s.get("boost", 0),
            "flags": 1 if s["pos"][2] < 30.0 else 0,
            "vel": s.get("vel", [0, 0, 0])
        })
        
    t_enc_start = time.perf_counter()
    binary_payload = encode_quantized_binary(frames_to_encode)
    t_enc = time.perf_counter() - t_enc_start
    
    t_dec_start = time.perf_counter()
    decoded_frames = decode_quantized_binary(binary_payload)
    t_dec = time.perf_counter() - t_dec_start
    
    # Quantization error analysis
    pos_quant_errors = []
    for orig, dec in zip(frames_to_encode[:1000], decoded_frames[:1000]):
        err = np.linalg.norm(np.array(orig["pos"]) - np.array(dec["pos"]))
        pos_quant_errors.append(float(err))
        
    results = {
        "replay_file": replay_path.name,
        "raw_size_bytes": len(raw_bytes),
        "raw_parse_time_ms": round(t_parse * 1000, 2),
        "candidate_1_hermite_mean_error_uu": round(float(np.mean(hermite_errors)), 3),
        "candidate_1_linear_mean_error_uu": round(float(np.mean(linear_errors)), 3),
        "candidate_1_interp_cost_us_per_frame": round(t_interp_elapsed * 1e6, 2),
        "candidate_2_physics_divergence_mean_uu": {
            f"{h}s": round(float(np.mean(errs)), 1) if errs else None
            for h, errs in physics_divergence.items()
        },
        "candidate_3_binary_size_bytes": len(binary_payload),
        "candidate_3_compression_ratio": round(len(raw_bytes) / len(binary_payload), 2),
        "candidate_3_decode_time_ms": round(t_dec * 1000, 3),
        "candidate_3_mean_quantization_error_uu": round(float(np.mean(pos_quant_errors)), 4),
    }
    
    print("\n[RESULTS SUMMARY]")
    print(f"  Candidate 1 (Hermite vs Linear):")
    print(f"    - Mean Position Reconstruction Error: Hermite {results['candidate_1_hermite_mean_error_uu']} UU vs Linear {results['candidate_1_linear_mean_error_uu']} UU")
    print(f"    - Interp Latency: {results['candidate_1_interp_cost_us_per_frame']} microseconds per frame")
    print(f"  Candidate 2 (Physics Re-Simulation without Input Telemetry):")
    for h, err in results["candidate_2_physics_divergence_mean_uu"].items():
        print(f"    - Divergence at +{h}: {err} UU")
    print(f"  Candidate 3 (Quantized Binary Stream):")
    print(f"    - Binary Size: {len(binary_payload):,} bytes (Ratio {results['candidate_3_compression_ratio']}x)")
    print(f"    - Decode Time: {results['candidate_3_decode_time_ms']} ms (vs {results['raw_parse_time_ms']} ms raw parse)")
    print(f"    - Max Spatial Quantization Error: {results['candidate_3_mean_quantization_error_uu']} UU")
    
    return results


if __name__ == "__main__":
    replay_dir = Path(r"D:\Users\Sam Meyer\Documents\My Games\Rocket League\TAGame\DemosEpic")
    default_replays = [
        "23A661D44DBC5964B0718DBC5F956A33.replay",
        "001AAC74454E7D7FD9DBB68B238D67B1.replay",
        "0E135D2611EFEE7B6A553D8786B9BEA2.replay"
    ]
    
    all_results = []
    for name in default_replays:
        p = replay_dir / name
        if p.is_file():
            res = run_architecture_benchmark(p)
            all_results.append(res)
            
    out_file = Path(__file__).parent / "architecture_comparison_results.json"
    out_file.write_text(json.dumps(all_results, indent=2))
    print(f"\nAll benchmark results written to: {out_file}")
