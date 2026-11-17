import test from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from 'three';
import {qualitySettings,createEffectRefiner,refineBoostPadVisuals} from '../src/visual-quality.js';

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

test('hide upstream giant black large-pad geometry without removing actual lens or pickup',()=>{
  const baseGroup={visible:true};
  const lens={visible:true};
  const big={userData:{isBig:true,baseGroup},visible:true};
  const small={userData:{isBig:false,baseGroup:{visible:true}},visible:true};
  const scene={children:[big,small]};
  assert.equal(refineBoostPadVisuals({scene}),1);
  assert.equal(baseGroup.visible,false);
  assert.equal(big.visible,true);
  assert.equal(lens.visible,true);
  assert.equal(small.userData.baseGroup.visible,true);
  assert.equal(refineBoostPadVisuals({scene}),0);
  // The upstream boost plugin may reenable its base group after cooldown.
  baseGroup.visible=true;
  assert.equal(refineBoostPadVisuals({scene}),1);
});
