/* Opens the separate native-WASM 3D player without touching Replay Lab's
 * existing coaching, preview timer, or server upload path.
 * The original .replay File is transferred between same-origin tabs only.
 */
(function(){
  'use strict';
  const button=document.getElementById('openHdReplay');
  const upload=document.getElementById('fileInput');
  const playerSelect=document.getElementById('playerSelect');
  if(!button || !upload)return;
  let lastReplayFile=null;
  let hdWindow=null;
  // Register in capture phase: legacy app clears input.value in its handler.
  upload.addEventListener('change',event=>{
    const file=event.target?.files?.[0];
    if(file && file.name.toLowerCase().endsWith('.replay'))lastReplayFile=file;
  },true);
  button.addEventListener('click',()=>{
    hdWindow=window.open('/hd','replay-lab-high-fidelity');
    if(hdWindow)hdWindow.focus();
  });
  window.addEventListener('message',event=>{
    if(event.origin!==location.origin || !hdWindow ||
       event.source!==hdWindow || event.data?.type!=='replay-lab:hd-ready')return;
    if(!lastReplayFile)return; // Standalone viewer has its own file picker.
    const choice=playerSelect?.selectedOptions?.[0]?.textContent||'';
    const preferredPlayer=choice.split(' — ')[0].trim();
    hdWindow.postMessage({
      type:'replay-lab:hd-load',file:lastReplayFile,preferredPlayer
    },location.origin);
  });
})();
