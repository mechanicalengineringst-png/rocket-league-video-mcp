/* Replay Lab 3D math: replay axes, full car attitude and non-clipping camera poses.
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
  const finiteRotation=r=>Array.isArray(r)&&r.length===3&&r.every(isnum);

  function basisFromRotation(rotation, rawForward){
    // glam::EulerRot::XYZ (Rx * Ry * Rz) used by the replay parser.
    // RL car +X=nose, RL +Y=left, RL +Z=roof.
    if(finiteRotation(rotation)){
      const [x,y,z]=rotation;
      const a=Math.cos(x),b=Math.sin(x),c=Math.cos(y),d=Math.sin(y),e=Math.cos(z),f=Math.sin(z);
      const front=[c*e,a*f+b*d*e,b*f-a*d*e];
      const left=[-c*f,a*e-b*d*f,b*e+a*d*f];
      const roof=[d,-b*c,a*c];
      const forward=rlToThree(front),up=rlToThree(roof);
      const right=scale(rlToThree(left),-1);
      return {right:norm(right),up:norm(up),forward:norm(forward),source:'rotation'};
    }
    if(!vec(rawForward))return null;
    // If pitch/roll telemetry is unavailable, use a level-car fallback;
    // never infer unrecorded roll from the direction of travel.
    const forward=norm(rlToThree(rawForward));
    const right=norm(cross([0,1,0],forward),[1,0,0]);
    const up=norm(cross(forward,right),[0,1,0]);
    return {right,up,forward,source:'forward-only'};
  }

  function planCamera(mode, car, ball, previousHorizontal){
    if(!car||!['pov','follow','ball'].includes(mode)||
       ![car.x,car.y,car.z].every(isnum))return null;
    const center=replayPosition(car),basis=basisFromRotation(car.rotation,car.forward);
    if(!basis)return null;
    let heading=[basis.forward[0],0,basis.forward[2]];
    if(Math.hypot(...heading)<0.15)heading=previousHorizontal||[0,0,-1];
    heading=norm(heading);
    const configs={
      follow:{distance:7.4,height:3.45,fov:84,targetHeight:1.15},
      pov:{distance:3.65,height:1.88,fov:94,targetHeight:1.0},
      ball:{distance:6.4,height:3.10,fov:92,targetHeight:1.05}
    };
    const cfg=configs[mode];
    let position=add(sub(center,scale(heading,cfg.distance)),[0,cfg.height,0]);
    let target=add(center,[0,cfg.targetHeight,0]);
    if(mode==='ball'&&ball&&[ball.x,ball.y,ball.z].every(isnum)){
      target=replayPosition(ball);
      // Do not anchor the camera *to the ball*. At a 50 or dribble that
      // puts a huge ball between the user and the play.
      const between=sub(position,target);
      const distance=Math.hypot(...between);
      if(distance<3.0){
        position=add(target,scale(norm(between,scale(heading,-1)),3.0));
      }
    }
    // Keep the camera outside the ground and below the arena roof.
    position[1]=Math.max(0.85,Math.min(19.2,position[1]));
    return {position,target,heading,fov:cfg.fov,basis,ballRadius:RADIUS};
  }

  function padCountdown(now,pickup,large){
    if(!isnum(now)||!isnum(pickup))return null;
    const duration=large?10:4;
    const remaining=pickup+duration-now;
    return remaining>0?{available:false,remaining,progress:Math.min(1,Math.max(0,1-remaining/duration))}:{available:true,remaining:0,progress:1};
  }

  const api={rlToThree,replayPosition,basisFromRotation,planCamera,padCountdown};
  root.ReplayLabViewMath=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof globalThis!=='undefined'?globalThis:this);
