
(function(){
  var themes={"arctic-console":"light","graphite-edge":"dark","midnight-signal":"dark","noc-vision":"dark","virtinfra-core":"dark"};
  var customKey="virtinfra-theme-selection-v4";
  var select=document.getElementById("unified-theme-select");
  function readCustom(){try{return localStorage.getItem(customKey)||""}catch(e){return""}}
  function writeCustom(id){try{if(id)localStorage.setItem(customKey,id);else localStorage.removeItem(customKey)}catch(e){}}
  function coreMode(){try{var mode=localStorage.getItem("bw-theme-mode")||"auto";return mode==="dark"||mode==="light"?mode:"auto"}catch(e){return"auto"}}
  function selectValue(value){if(select)select.value=value}
  function useCore(mode,persist){
    mode=(mode==="dark"||mode==="light")?mode:"auto";
    writeCustom("");
    document.documentElement.removeAttribute("data-custom-theme");
    if(typeof applyTheme==="function")applyTheme(mode,!!persist);
    else{
      try{if(persist)localStorage.setItem("bw-theme-mode",mode)}catch(e){}
      document.documentElement.setAttribute("data-theme-mode",mode);
      var resolved=mode;
      if(mode==="auto"&&window.matchMedia)resolved=window.matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light";
      document.documentElement.setAttribute("data-theme",resolved);
    }
    selectValue("mode:"+mode);
  }
  function useCustom(id,persist){
    if(!themes[id]){useCore(coreMode(),false);return}
    if(persist)writeCustom(id);
    document.documentElement.setAttribute("data-custom-theme",id);
    document.documentElement.setAttribute("data-theme",themes[id]);
    document.documentElement.setAttribute("data-theme-mode","custom");
    selectValue("theme:"+id);
  }
  function applySelection(value,persist){
    if(value&&value.indexOf("theme:")===0)useCustom(value.slice(6),persist);
    else useCore(value&&value.indexOf("mode:")===0?value.slice(5):"auto",persist);
  }
  if(select)select.addEventListener("change",function(){applySelection(this.value,true)});
  window.addEventListener("storage",function(ev){
    if(ev.key===customKey||ev.key==="bw-theme-mode"){
      var id=readCustom();if(id&&themes[id])useCustom(id,false);else useCore(coreMode(),false);
    }
  });
  var current=readCustom();if(current&&themes[current])useCustom(current,false);else useCore(coreMode(),false);
})();
