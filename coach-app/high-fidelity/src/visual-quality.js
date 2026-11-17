import * as THREE from 'three';

/** Progressive, reversible quality pass on the ACTUAL GLTF scene/materials.
 * Preserve GLTFLoader's baseColor color-space settings, normal maps and decals.
 * Do not fabricate texture files or change stadium geometry.
 */
const maps = ['map','emissiveMap','normalMap','roughnessMap',
  'metalnessMap','aoMap','alphaMap','bumpMap'];
const settings = {
  performance:{ratio:1,anisotropy:2},
  balanced:{ratio:1.5,anisotropy:8},
  sharp:{ratio:2,anisotropy:16},
};
export function qualitySettings(name, dpr=1, maxAniso=16) {
  const profile=settings[name] || settings.balanced;
  return {
    // Sharp is an explicit quality override, including on common 1x-DPR
    // monitors where the old min(profile,dpr) could never supersample.
    // Other modes respect native screen density to avoid needless GPU work.
    ratio:name==='sharp' ? 2 : Math.max(1,Math.min(profile.ratio,Number(dpr)||1)),
    anisotropy:Math.max(1,Math.min(profile.anisotropy,Number(maxAniso)||1)),
  };
}
export function applySceneQuality(player, name='balanced') {
  const renderer=player?.renderer;
  if (!renderer || !player?.scene) return {textures:0,meshes:0,ratio:1};
  const max=renderer.capabilities?.getMaxAnisotropy?.() ?? 1;
  const {ratio,anisotropy}=qualitySettings(name,window.devicePixelRatio||1,max);
  if (typeof renderer.setPixelRatio==='function') renderer.setPixelRatio(ratio);
  // Stadium PBR geometry should RECEIVE shadows, not cast giant, hard-edged
  // shape shadows across its own floor. Preserve actor/car shadow casting.
  let disabledArenaCasters=0;
  for(const mesh of player.arenaManager?.arenaMeshes ?? []){
    if(mesh?.castShadow){mesh.castShadow=false;disabledArenaCasters++;}
  }
  const done=new Set();
  let meshes=0;
  player.scene.traverse(obj=>{
    if (!obj.isMesh) return;
    meshes++;
    const materials=Array.isArray(obj.material)?obj.material:[obj.material];
    for (const mat of materials) {
      if (!mat) continue;
      for (const field of maps) {
        const t=mat[field];
        if (!t?.isTexture || done.has(t)) continue;
        done.add(t);
        const sampler=t.minFilter;
        // Filter near camera and at grazing angles; leave packed color
        // spaces and alpha/depth behavior chosen by the GLTF author alone.
        t.magFilter=THREE.LinearFilter;
        if (sampler===THREE.NearestFilter || sampler===THREE.NearestMipmapNearestFilter)
          t.minFilter=THREE.LinearMipmapLinearFilter;
        t.anisotropy=anisotropy;
        t.needsUpdate=true;
      }
    }
  });
  return {textures:done.size,meshes,ratio,anisotropy,disabledArenaCasters};
}

function getEffectCollections(player) {
  const effects=player?.effectsManager;
  return {
    boost:effects?.boostTrails instanceof Map?[...effects.boostTrails.values()]:[],
    supersonic:effects?.supersonicTrails instanceof Map?[...effects.supersonicTrails.values()]:[],
  };
}

/** Optional, non-destructive patch to the upstream particle shaders.
 * We retain exact originals and can restore them on quality-toggle.
 */
export function createEffectRefiner(getPreference=()=> 'soft') {
  const originals=new WeakMap();
  const applied=new WeakMap();
  // Only remember visibility while our Off override is active. Source
  // effects can appear/disappear every frame; a permanently cached initial
  // false would suppress future legitimate boosts and supersonic trails.
  const hiddenByUs=new WeakMap();
  function setVisibility(target,visible) {
    if(!target) return;
    if(!visible) {
      if(!hiddenByUs.has(target)) hiddenByUs.set(target,target.visible);
      target.visible=false;
    } else if(hiddenByUs.has(target)) {
      target.visible=hiddenByUs.get(target);
      hiddenByUs.delete(target);
    }
    // Otherwise preserve the upstream frame's live visibility as-is.
  }
  const originalRibbonWidth=new WeakMap();
  let changes=0;
  function materialStyle(mat,kind,style) {
    if (!mat?.isShaderMaterial) return;
    if (!originals.has(mat)) originals.set(mat,{
      vertex:mat.vertexShader,fragment:mat.fragmentShader
    });
    if (applied.get(mat)===style) return;
    const original=originals.get(mat);
    let vertex=original.vertex,fragment=original.fragment;
    if (style==='soft' && kind==='boost') {
      vertex=vertex.replace(
        /gl_PointSize\s*=\s*size\s*\*\s*\(2500\.0\s*\/\s*-mvPosition\.z\)\s*;/,
        'gl_PointSize = clamp(size * (1750.0 / max(1.0, -mvPosition.z)), 1.0, 15.0);'
      );
      // Soft incandescent center, reduced oversaturation and aliasing.
      fragment=fragment.replace(
        'gl_FragColor = vec4(flameColor * glow * 1.5, vAlpha * glow);',
        'gl_FragColor = vec4(flameColor * glow * 1.1, vAlpha * glow * 0.85);'
      );
    }
    if (style==='soft' && kind==='supersonic') {
      fragment=fragment.replace(
        /gl_FragColor\s*=\s*vColor\s*\*\s*textureColor\s*;/,
        [
          'vec4 shade = vColor * textureColor;',
          'float edge = smoothstep(0.0, 0.18, vUV.y) *',
          '             (1.0 - smoothstep(0.76, 1.0, vUV.y));',
          'gl_FragColor = vec4(shade.rgb, shade.a * edge * 0.66);'
        ].join('\n')
      );
    }
    if(mat.vertexShader!==vertex || mat.fragmentShader!==fragment) {
      mat.vertexShader=vertex;
      mat.fragmentShader=fragment;
      mat.needsUpdate=true;
      changes++;
    }
    applied.set(mat,style);
  }
  function update(player) {
    const preference=getPreference();
    const style=preference==='soft'?'soft':'original';
    const visible=preference!=='off';
    const effect=getEffectCollections(player);
    for (const trail of effect.boost) {
      if (trail?.points) {
        setVisibility(trail.points,visible);
        materialStyle(trail.points.material,'boost',style);
      }
    }
    for (const trail of effect.supersonic) {
      if (typeof trail.trailWidth==='number' && !originalRibbonWidth.has(trail))
        originalRibbonWidth.set(trail,trail.trailWidth);
      if (originalRibbonWidth.has(trail))
        trail.trailWidth=preference==='soft'
          ? Math.min(9,originalRibbonWidth.get(trail))
          : originalRibbonWidth.get(trail);
      for (const segment of trail?.segments ?? []) {
        for (const ribbon of [segment.leftTrail,segment.rightTrail]) {
          if(ribbon?.mesh) setVisibility(ribbon.mesh,visible);
          if(ribbon?.material) materialStyle(ribbon.material,'supersonic',style);
        }
      }
    }
    return changes;
  }
  return {update,get shaderUpdates(){return changes;}};
}

/** The stadium GLTF stacks several Field_STD_Floor_Hex*
 * decorations over the playing surface. Controlled same-frame screenshots
 * implicated this family in the intrusive dark/blue field polygons. Hide
 * only these visual overlays in Clean mode; preserve grass, field lines,
 * gameplay pads and actors. Original restores all these meshes. A final
 * visual replay comparison is still required to confirm the appearance.
 */
export function setFieldDecorStyle(player,style='clean') {
  let changed=0;
  for(const mesh of player?.arenaManager?.arenaMeshes ?? []){
    if(typeof mesh.name==='string' && mesh.name.startsWith('Field_STD_Floor_Hex')){
      const visible=style==='original';
      if(mesh.visible!==visible){mesh.visible=visible;changed++;}
    }
  }
  return changed;
}

export function createVisualEffectsPlugin(refiner) {
  return {
    id:'replay-lab-effects-polish',
    beforeRender(ctx) {
      refiner?.update(ctx.player);
    },
  };
}
