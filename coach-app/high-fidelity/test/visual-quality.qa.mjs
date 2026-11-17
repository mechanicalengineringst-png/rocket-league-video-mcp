import test from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from 'three';
import {qualitySettings,createEffectRefiner,setFieldDecorStyle} from '../src/visual-quality.js';

test('graphics mode respects hardware pixel ratio and anisotropy ceilings',()=>{
  assert.deepEqual(qualitySettings('balanced',1,4),{ratio:1,anisotropy:4});
  assert.deepEqual(qualitySettings('sharp',3,16),{ratio:2,anisotropy:16});
  assert.deepEqual(qualitySettings('performance',2,1),{ratio:1,anisotropy:1});
  assert.deepEqual(qualitySettings('sharp',1,16),{ratio:2,anisotropy:16});
});
test('soft boost particle shader is bounded and can restore the source',()=>{
  const mat=new THREE.ShaderMaterial({
    vertexShader:'void main(){ gl_PointSize = size * (2500.0 / -mvPosition.z); }',
    fragmentShader:'void main(){ gl_FragColor = vec4(flameColor * glow * 1.5, vAlpha * glow); }'
  });
  const points={visible:true,material:mat};
  const effects={boostTrails:new Map([[1,{points}]]),supersonicTrails:new Map()};
  let profile='soft';
  const ref=createEffectRefiner(()=>profile);
  ref.update({effectsManager:effects});
  assert.match(mat.vertexShader,/clamp\(size/);
  assert.doesNotMatch(mat.fragmentShader,/glow \* 1\.5/);
  profile='original';ref.update({effectsManager:effects});
  assert.match(mat.vertexShader,/2500\.0/);
  profile='off';ref.update({effectsManager:effects});
  assert.equal(points.visible,false);
  profile='soft';ref.update({effectsManager:effects});
  assert.equal(points.visible,true);
});
test('soft ribbon shader updates actual supersonic trail material',()=>{
  const fragment='varying vec2 vUV; varying vec4 vColor; void main(){vec4 textureColor = texture2D(trailTexture,vUV); gl_FragColor = vColor * textureColor;}';
  const mat=new THREE.ShaderMaterial({vertexShader:'void main(){}',fragmentShader:fragment});
  const trail={mesh:{visible:true},material:mat};
  const supersonic={trailWidth:15,segments:[{leftTrail:trail,rightTrail:null}]};
  const effects={boostTrails:new Map(),supersonicTrails:new Map([[1,supersonic]])};
  let pref='soft';
  const ref=createEffectRefiner(()=>pref);
  ref.update({effectsManager:effects});
  assert.equal(supersonic.trailWidth,9);
  assert.match(mat.fragmentShader,/edge/);
  pref='original';ref.update({effectsManager:effects});
  assert.equal(supersonic.trailWidth,15);
  assert.equal(mat.fragmentShader,fragment);
});


test('Clean field removes all stacked hex decals but not grass, lines, or boost pads',()=>{
  const hexA={name:'Field_STD_Floor_Hex',visible:true};
  const hexB={name:'Field_STD_Floor_Hex001',visible:true};
  const hexC={name:'Field_STD_Floor_Hex002',visible:true};
  const grass={name:'Field_STD_Floor_Thick001',visible:true};
  const lines={name:'Field_STD_Floor_Thick003',visible:true};
  const boost={name:'BigPadArt',visible:true};
  const player={arenaManager:{arenaMeshes:[hexA,hexB,hexC,grass,lines,boost]}};
  assert.equal(setFieldDecorStyle(player,'clean'),3);
  assert.ok([hexA,hexB,hexC].every(mesh=>mesh.visible===false));
  assert.ok([grass,lines,boost].every(mesh=>mesh.visible===true));
  assert.equal(setFieldDecorStyle(player,'clean'),0);
  assert.equal(setFieldDecorStyle(player,'original'),3);
  assert.ok([hexA,hexB,hexC,grass,lines,boost].every(mesh=>mesh.visible===true));
});

test('trail settings restore original widths and visibility, including originally hidden effects',()=>{
  const shader=new THREE.ShaderMaterial({
    vertexShader:'void main(){}',fragmentShader:'void main(){}'
  });
  const originalHidden={visible:false,material:shader};
  const originalVisible={visible:true,material:shader};
  const hiddenRibbon={mesh:{visible:false},material:shader};
  const visibleRibbon={mesh:{visible:true},material:shader};
  const supersonic={trailWidth:22,segments:[{leftTrail:hiddenRibbon,rightTrail:visibleRibbon}]};
  const effects={
    boostTrails:new Map([[1,{points:originalHidden}],[2,{points:originalVisible}]]),
    supersonicTrails:new Map([[1,supersonic]]),
  };
  let selected='soft';
  const refine=createEffectRefiner(()=>selected);
  const player={effectsManager:effects};
  refine.update(player);
  assert.equal(supersonic.trailWidth,9);
  assert.equal(originalHidden.visible,false);
  assert.equal(visibleRibbon.mesh.visible,true);
  // Native effect manager may turn on a previously absent emitter at the
  // next replay frame. Soft mode must not freeze its visibility forever.
  originalHidden.visible=true;
  refine.update(player);
  assert.equal(originalHidden.visible,true,'an active native boost is not suppressed by a cached frame-zero state');
  originalHidden.visible=false;
  selected='off';refine.update(player);
  assert.equal(originalVisible.visible,false);
  assert.equal(visibleRibbon.mesh.visible,false);
  selected='original';refine.update(player);
  assert.equal(supersonic.trailWidth,22,'original trail width must not be overwritten with a guessed constant');
  assert.equal(originalHidden.visible,false,'an effect hidden before refinement must stay hidden');
  assert.equal(hiddenRibbon.mesh.visible,false);
  assert.equal(originalVisible.visible,true);
  assert.equal(visibleRibbon.mesh.visible,true);
});
