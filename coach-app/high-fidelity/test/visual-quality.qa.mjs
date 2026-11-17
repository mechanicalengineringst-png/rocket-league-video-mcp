import test from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from 'three';
import {qualitySettings,createEffectRefiner,setFieldDecorStyle} from '../src/visual-quality.js';

test('graphics mode respects hardware pixel ratio and anisotropy ceilings',()=>{
  assert.deepEqual(qualitySettings('balanced',1,4),{ratio:1,anisotropy:4});
  assert.deepEqual(qualitySettings('sharp',3,16),{ratio:2,anisotropy:16});
  assert.deepEqual(qualitySettings('performance',2,1),{ratio:1,anisotropy:1});
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


test('field decoration toggle hides only raycast-identified dark decal',()=>{
  const decor={name:'Field_STD_Floor_Hex002',visible:true};
  const grass={name:'Field_STD_Floor_Thick001',visible:true};
  const boost={name:'BigPadArt',visible:true};
  const player={arenaManager:{arenaMeshes:[decor,grass,boost]}};
  assert.equal(setFieldDecorStyle(player,'clean'),1);
  assert.equal(decor.visible,false);
  assert.equal(grass.visible,true);
  assert.equal(boost.visible,true);
  assert.equal(setFieldDecorStyle(player,'clean'),0);
  assert.equal(setFieldDecorStyle(player,'original'),1);
  assert.equal(decor.visible,true);
});
