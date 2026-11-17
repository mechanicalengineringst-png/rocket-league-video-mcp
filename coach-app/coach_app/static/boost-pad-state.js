/* Replay Lab: deterministic, scrub-safe boost-pad timeline evaluator.
 * Separate from playback/camera math so the 3D renderer can be replaced.
 */
(function(root){
  'use strict';
  function finite(n){return typeof n==='number' && Number.isFinite(n);}
  function lastAtOrBefore(sorted,t){
    let lo=0, hi=sorted.length;
    while(lo<hi){const mid=(lo+hi)>>1;if(sorted[mid]<=t)lo=mid+1;else hi=mid;}
    return lo>0?sorted[lo-1]:null;
  }
  function compile(data){
    if(!data || data.schema!=='replay-lab/boost-pads-v1' ||
       !Array.isArray(data.pads) || data.pads.length!==34)return null;
    const pads=data.pads.map((p,i)=>{
      if(!p || p.id!==i || !finite(p.x) || !finite(p.y) ||
         typeof p.big!=='boolean' || ![4,10].includes(p.respawnSeconds))return null;
      return {id:i,x:p.x,y:p.y,big:p.big,cooldown:p.respawnSeconds};
    });
    if(pads.some(p=>p===null))return null;
    const perPad=pads.map(()=>[]);
    const resets=(Array.isArray(data.resets)?data.resets:[])
      .filter(finite).sort((a,b)=>a-b);
    for(const e of (Array.isArray(data.pickups)?data.pickups:[])){
      if(!e || !Number.isInteger(e.padId) || !pads[e.padId] || !finite(e.t))continue;
      perPad[e.padId].push(e.t);
    }
    perPad.forEach(a=>a.sort((a,b)=>a-b));
    return {
      pads,perPad,resets,source:data.source==='native-boost-pickups'?'native':'unavailable',
      observedPickupCount:Number(data.observedPickupCount)||0,
      unmatchedPickupCount:Number(data.unmatchedPickupCount)||0
    };
  }
  function at(model,padId,t){
    if(!model || !model.pads[padId] || !finite(t) || model.source!=='native'){
      return {known:false,available:null,remaining:null,progress:0,respawnAge:null};
    }
    const reset=lastAtOrBefore(model.resets,t);
    const pickup=lastAtOrBefore(model.perPad[padId],t);
    // An authoritative kickoff reset or matched pickup is needed before
    // claiming the pad is in a particular state.
    if(reset===null && pickup===null){
      return {known:false,available:null,remaining:null,progress:0,respawnAge:null};
    }
    if(pickup===null || (reset!==null && pickup < reset)){
      return {known:true,available:true,remaining:0,progress:1,respawnAge:null};
    }
    const duration=model.pads[padId].cooldown;
    const remaining=Math.max(0,pickup+duration-t);
    const respawnAge=t-(pickup+duration);
    return {
      known:true,available:remaining===0,remaining,
      progress:Math.max(0,Math.min(1,1-remaining/duration)),
      respawnAge:respawnAge>=0?respawnAge:null
    };
  }
  function describe(model){
    if(!model || model.source!=='native')return 'Pad pickup data unavailable — state unknown';
    const count=model.observedPickupCount;
    const matched=Math.max(0,count-model.unmatchedPickupCount);
    return 'Boost pad pickups: '+matched+'/'+count+
      ' mapped from native events'+(model.unmatchedPickupCount?' · some states uncertain':'')+
      ' · pad ID inferred from pickup location';
  }
  const api={compile,at,describe,lastAtOrBefore};
  root.ReplayLabBoostPadState=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof globalThis!=='undefined'?globalThis:this);
