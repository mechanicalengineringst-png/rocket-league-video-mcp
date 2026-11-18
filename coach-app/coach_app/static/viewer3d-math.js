/* Replay Lab 3D math: replay axes, continuous interpolation, and non-clipping camera poses.
 * This module is dependency-free so node can test it without WebGL.
 * Rocket League uses X/Y horizontal and Z up. The app's Three scene uses
 * (-X, Z, -Y), which includes a handedness change.
 */
(function(root){
  'use strict';
  const RADIUS=0.92;
  const isnum=Number.isFinite;
  const vec=v=>Array.isArray(v)&&v.length===3&&v.every(isnum);
  const dot=(a,b)=>a[0]*b[0]+a[1]*b[1]+a[2]*b[2];
  const sub=(a,b)=>a.map((v,i)=>v-b[i]);
  const add=(a,b)=>a.map((v,i)=>v+b[i]);
  const scale=(a,k)=>a.map(v=>v*k);
  const cross=(a,b)=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
  const norm=(a,fallback=[0,0,1])=>{const m=Math.hypot(...a);return m>1e-6?scale(a,1/m):fallback.slice();};
  const rlToThree=v=>[-v[0],v[2],-v[1]];
  const replayPosition=c=>[Number(c.x)*0.01,Number(c.z)*0.01,Number(c.y)*0.01].map((v,i)=>i===0||i===2?-v:v);
  const replayVelocity=c=>(Array.isArray(c?.velocity)&&c.velocity.length===3&&c.velocity.every(isnum))
    ?[-c.velocity[0]*0.01,c.velocity[2]*0.01,-c.velocity[1]*0.01]:null;
  const finiteRotation=r=>Array.isArray(r)&&r.length===3&&r.every(isnum);

  function basisFromRotation(rotation, rawForward){
    // glam::EulerRot::XYZ (Rx * Ry * Rz) used by the replay parser.
    // RL car: +X=nose, +Y=right, +Z=roof.
    if(finiteRotation(rotation)){
      const [x,y,z]=rotation;
      const a=Math.cos(x),b=Math.sin(x),c=Math.cos(y),d=Math.sin(y),e=Math.cos(z),f=Math.sin(z);
      // Columns of Rx(x)*Ry(y)*Rz(z):
      const col0=[c*e, a*f + b*d*e, b*f - a*d*e]; // RL car nose (+X)
      const col2=[d, -b*c, a*c];                  // RL car roof (+Z)
      
      const forward=norm(rlToThree(col0));
      const upRaw=norm(rlToThree(col2));
      // In Three.js (reflected by rlToThree), the right vector that preserves
      // det=1 and cross(right, up) = forward is:
      const right=norm(cross(upRaw,forward));
      const up=norm(cross(forward,right));
      return {right,up,forward,source:'rotation'};
    }
    if(!vec(rawForward))return null;
    const forward=norm(rlToThree(rawForward));
    const right=norm(cross([0,1,0],forward),[1,0,0]);
    const up=norm(cross(forward,right),[0,1,0]);
    return {right,up,forward,source:'forward-only'};
  }

  function quatFromBasis(right, up, forward){
    const m00=right[0], m01=up[0], m02=forward[0];
    const m10=right[1], m11=up[1], m12=forward[1];
    const m20=right[2], m21=up[2], m22=forward[2];
    const trace=m00+m11+m22;
    let qx, qy, qz, qw;
    if(trace>0){
      const s=0.5/Math.sqrt(trace+1.0);
      qw=0.25/s;
      qx=(m21-m12)*s;
      qy=(m02-m20)*s;
      qz=(m10-m01)*s;
    }else if(m00>m11&&m00>m22){
      const s=2.0*Math.sqrt(1.0+m00-m11-m22);
      qw=(m21-m12)/s;
      qx=0.25*s;
      qy=(m01+m10)/s;
      qz=(m02+m20)/s;
    }else if(m11>m22){
      const s=2.0*Math.sqrt(1.0+m11-m00-m22);
      qw=(m02-m20)/s;
      qx=(m01+m10)/s;
      qy=0.25*s;
      qz=(m12+m21)/s;
    }else{
      const s=2.0*Math.sqrt(1.0+m22-m00-m11);
      qw=(m10-m01)/s;
      qx=(m02+m20)/s;
      qy=(m12+m21)/s;
      qz=0.25*s;
    }
    return [qx,qy,qz,qw];
  }

  function quatSlerp(q0, q1, t){
    let cosHalfTheta = q0[0]*q1[0] + q0[1]*q1[1] + q0[2]*q1[2] + q0[3]*q1[3];
    let q1Copy = q1.slice();
    if(cosHalfTheta < 0){
      q1Copy = [-q1[0], -q1[1], -q1[2], -q1[3]];
      cosHalfTheta = -cosHalfTheta;
    }
    if(Math.abs(cosHalfTheta) >= 1.0){
      return q0.slice();
    }
    const halfTheta = Math.acos(Math.min(1.0, Math.max(-1.0, cosHalfTheta)));
    const sinHalfTheta = Math.sqrt(Math.max(0, 1.0 - cosHalfTheta * cosHalfTheta));
    if(Math.abs(sinHalfTheta) < 0.001){
      return [
        q0[0]*(1-t) + q1Copy[0]*t,
        q0[1]*(1-t) + q1Copy[1]*t,
        q0[2]*(1-t) + q1Copy[2]*t,
        q0[3]*(1-t) + q1Copy[3]*t
      ];
    }
    const ratioA = Math.sin((1-t)*halfTheta) / sinHalfTheta;
    const ratioB = Math.sin(t*halfTheta) / sinHalfTheta;
    return [
      q0[0]*ratioA + q1Copy[0]*ratioB,
      q0[1]*ratioA + q1Copy[1]*ratioB,
      q0[2]*ratioA + q1Copy[2]*ratioB,
      q0[3]*ratioA + q1Copy[3]*ratioB
    ];
  }

  function basisFromQuat(q){
    const [x,y,z,w]=q;
    const x2=x+x, y2=y+y, z2=z+z;
    const xx=x*x2, xy=x*y2, xz=x*z2;
    const yy=y*y2, yz=y*z2, zz=z*z2;
    const wx=w*x2, wy=w*y2, wz=w*z2;
    const right=[1-(yy+zz), xy+wz, xz-wy];
    const up=[xy-wz, 1-(xx+zz), yz+wx];
    const forward=[xz+wy, yz-wx, 1-(xx+yy)];
    return {right, up, forward};
  }

  function hermiteInterpolate(p0, v0, p1, v1, dt, s){
    if(!v0 || !v1 || dt <= 0 || dt > 0.35){
      return p0.map((v, i) => v + (p1[i] - v) * s);
    }
    // Check for physical teleport / goal reset / demolition
    const expectedDist = Math.hypot(...sub(p1, p0));
    const speed = Math.hypot(...v0);
    if(expectedDist > Math.max(8.0, speed * dt * 2.5)){
      return p0.map((v, i) => v + (p1[i] - v) * s);
    }
    const s2 = s * s, s3 = s2 * s;
    const h00 = 2 * s3 - 3 * s2 + 1;
    const h10 = s3 - 2 * s2 + s;
    const h01 = -2 * s3 + 3 * s2;
    const h11 = s3 - s2;
    return [0, 1, 2].map(i =>
      h00 * p0[i] + h10 * (v0[i] * dt) + h01 * p1[i] + h11 * (v1[i] * dt)
    );
  }

  function sampleReplayState(frames, time){
    if(!Array.isArray(frames) || !frames.length) return null;
    if(frames.length === 1 || time <= frames[0].t) return frames[0];
    const last = frames[frames.length - 1];
    if(time >= last.t) return last;

    // Binary search bounding frames
    let lo = 0, hi = frames.length - 1;
    while(lo < hi - 1){
      const mid = (lo + hi) >> 1;
      if(frames[mid].t <= time) lo = mid;
      else hi = mid;
    }
    const f0 = frames[lo], f1 = frames[hi];
    const dt = f1.t - f0.t;
    if(dt <= 1e-5) return f0;
    const s = Math.min(1, Math.max(0, (time - f0.t) / dt));

    // Interpolate ball
    const ball0 = f0.ball, ball1 = f1.ball;
    let ball = ball0;
    if(ball0 && ball1){
      const bp0 = [ball0.x, ball0.y, ball0.z];
      const bp1 = [ball1.x, ball1.y, ball1.z];
      const bv0 = Array.isArray(ball0.velocity) ? ball0.velocity : null;
      const bv1 = Array.isArray(ball1.velocity) ? ball1.velocity : null;
      const bp = hermiteInterpolate(bp0, bv0, bp1, bv1, dt, s);
      const bvel = bv0 && bv1 ? bv0.map((v, i) => v + (bv1[i] - v) * s) : bv0 || bv1;
      ball = {
        x: bp[0], y: bp[1], z: bp[2],
        velocity: bvel
      };
    }

    // Interpolate cars
    const cars = {};
    const pids = new Set([...Object.keys(f0.cars || {}), ...Object.keys(f1.cars || {})]);
    for(const pid of pids){
      const c0 = f0.cars?.[pid], c1 = f1.cars?.[pid];
      if(!c0) { if(c1) cars[pid] = c1; continue; }
      if(!c1) { cars[pid] = c0; continue; }
      if(c0.demolished || c1.demolished){
        cars[pid] = s < 0.5 ? c0 : c1;
        continue;
      }
      const cp0 = [c0.x, c0.y, c0.z];
      const cp1 = [c1.x, c1.y, c1.z];
      const cv0 = Array.isArray(c0.velocity) ? c0.velocity : null;
      const cv1 = Array.isArray(c1.velocity) ? c1.velocity : null;
      const cp = hermiteInterpolate(cp0, cv0, cp1, cv1, dt, s);
      const cvel = cv0 && cv1 ? cv0.map((v, i) => v + (cv1[i] - v) * s) : cv0 || cv1;

      // Rotation interpolation via Quaternion SLERP
      let rotation = c0.rotation, forward = c0.forward, quat = null;
      if(finiteRotation(c0.rotation) && finiteRotation(c1.rotation)){
        const b0 = basisFromRotation(c0.rotation);
        const b1 = basisFromRotation(c1.rotation);
        const q0 = quatFromBasis(b0.right, b0.up, b0.forward);
        const q1 = quatFromBasis(b1.right, b1.up, b1.forward);
        quat = quatSlerp(q0, q1, s);
        // Lerp Euler as fallback
        rotation = c0.rotation.map((v, i) => v + (c1.rotation[i] - v) * s);
        const bInterp = basisFromQuat(quat);
        // Convert Three forward back to RL forward for 2D map
        forward = [-bInterp.forward[0], -bInterp.forward[2], bInterp.forward[1]];
      }

      cars[pid] = {
        x: cp[0], y: cp[1], z: cp[2],
        velocity: cvel,
        rotation,
        forward,
        quaternion: quat,
        boost: isnum(c0.boost) && isnum(c1.boost) ? c0.boost + (c1.boost - c0.boost) * s : (c0.boost ?? c1.boost),
        jumpActive: s < 0.5 ? c0.jumpActive : c1.jumpActive,
        steer: c0.steer,
        throttle: c0.throttle
      };
    }

    return { t: time, ball, cars };
  }

  function planCamera(mode, car, ball, previousHorizontal, options={}){
    if(!car||!['pov','follow','ball'].includes(mode)||
       ![car.x,car.y,car.z].every(isnum))return null;
    const center=replayPosition(car);
    const basis=basisFromRotation(car.rotation,car.forward);
    if(!basis)return null;

    // Movement heading vs instantaneous attitude heading:
    // When flipping or aerial tumbling, use direction of travel so camera
    // stays smoothly behind the car without snapping 180° upside down.
    const vel=replayVelocity(car);
    const horizVel=vel?[vel[0],0,vel[2]]:null;
    const speedHoriz=horizVel?Math.hypot(...horizVel):0;

    let heading;
    if(speedHoriz>1.2){
      heading=norm(horizVel);
    }else{
      let h=[basis.forward[0],0,basis.forward[2]];
      if(Math.hypot(...h)<0.15)h=previousHorizontal||[0,0,-1];
      heading=norm(h);
    }

    // Authentic Rocket League tournament camera profiles (scale 0.01 = 100 uu):
    // Standard pro profile: FOV 110, Distance 270, Height 100, Angle -3° to -4°.
    const configs={
      follow:{distance:5.8,height:2.40,fov:86,targetHeight:0.85},
      pov:{distance:2.70,height:1.02,fov:105,targetHeight:0.65},
      ball:{distance:2.85,height:1.10,fov:108,targetHeight:0.65}
    };
    const cfg=configs[mode];

    // Wall-driving adaptation:
    // Blend camera up vector with car's roof vector so on walls the camera
    // pushes out into the arena instead of clipping through the wall or floor.
    const onWall = basis.up[1] < 0.75;
    const camUp = onWall ? norm(add(scale([0,1,0], 0.35), scale(basis.up, 0.65))) : [0,1,0];

    let position=add(sub(center,scale(heading,cfg.distance)),scale(camUp,cfg.height));
    let target=add(center,scale(camUp,cfg.targetHeight));

    if(mode==='ball'&&ball&&[ball.x,ball.y,ball.z].every(isnum)){
      target=replayPosition(ball);
      const toBall=sub(target,center);
      const dist=Math.hypot(...toBall);
      const dirToBall=dist>1e-4?norm(toBall):heading;
      // Anchor camera behind car relative to the ball
      position=add(sub(center,scale(dirToBall,cfg.distance)),scale(camUp,cfg.height));
      const between=sub(position,target);
      const distance=Math.hypot(...between);
      if(distance<2.5){
        position=add(target,scale(norm(between,scale(heading,-1)),2.5));
      }
    }
    // Arena boundaries: keep outside floor and below ceiling
    position[1]=Math.max(0.45,Math.min(19.2,position[1]));
    return {position,target,heading,fov:cfg.fov,basis,camUp,ballRadius:RADIUS};
  }

  function padCountdown(now,pickup,large){
    if(!isnum(now)||!isnum(pickup))return null;
    const duration=large?10:4;
    const remaining=pickup+duration-now;
    return remaining>0?{available:false,remaining,progress:Math.min(1,Math.max(0,1-remaining/duration))}:{available:true,remaining:0,progress:1};
  }

  function padStateAt(timeline, padId, time){
    if(!timeline || !Array.isArray(timeline.pads) || !timeline.pads[padId]){
      return {available: true, remaining: 0.0};
    }
    const pad = timeline.pads[padId];
    const duration = pad.big ? 10 : 4;
    let recent = null;
    if(Array.isArray(timeline.resets)){
      for(const reset of timeline.resets){
        if(reset <= time && (recent === null || reset > recent)){
          recent = reset;
        }
      }
    }
    let last = null;
    if(Array.isArray(timeline.pickups)){
      for(const pickup of timeline.pickups){
        if(pickup.padId === padId && pickup.t <= time){
          if(recent === null || pickup.t >= recent){
            last = pickup.t;
          }
        }
      }
    }
    if(last === null){
      return {available: true, remaining: 0.0};
    }
    const remaining = Math.max(0.0, last + duration - time);
    return {available: remaining <= 0.0, remaining: Math.round(remaining * 1000) / 1000};
  }

  const api={
    rlToThree,replayPosition,replayVelocity,basisFromRotation,
    quatFromBasis,quatSlerp,basisFromQuat,hermiteInterpolate,
    sampleReplayState,planCamera,padCountdown,padStateAt
  };
  root.ReplayLabViewMath=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof globalThis!=='undefined'?globalThis:this);
