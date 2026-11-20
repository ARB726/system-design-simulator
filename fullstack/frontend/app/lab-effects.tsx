'use client';

import { memo, useEffect, useRef, useState } from 'react';
import { LazyMotion, MotionConfig } from 'motion/react';
import * as m from 'motion/react-m';
import { Pause, Play, Sparkles } from 'lucide-react';

const loadAnimations=()=>import('motion/react').then(module=>module.domAnimation);

export function LabMotion({children}:{children:React.ReactNode}) {
  return <LazyMotion features={loadAnimations} strict><MotionConfig reducedMotion="user" transition={{duration:.4,ease:[.22,1,.36,1]}}>{children}</MotionConfig></LazyMotion>;
}

export const LabScene = memo(function LabScene() {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [paused,setPaused] = useState(false);
  useEffect(()=>{
    document.documentElement.dataset.ambientPaused=String(paused);
    return ()=>{delete document.documentElement.dataset.ambientPaused;};
  },[paused]);
  useEffect(()=>{
    const element=canvas.current;
    const context=element?.getContext('2d');
    if(!element||!context)return;
    const media=window.matchMedia('(prefers-reduced-motion: reduce)');
    let frame=0, width=0, height=0, time=0, previous=0;
    const mobile=window.matchMedia('(max-width: 550px)').matches;
    const frameInterval=mobile?66:40;
    const points=Array.from({length:mobile?18:42},(_,i)=>({x:((i*73+17)%101)/101,y:((i*41+13)%103)/103,phase:i*1.7}));
    function draw(stamp:number){
      if(!context||!element)return;
      if(stamp-previous<frameInterval){frame=requestAnimationFrame(draw);return;}
      previous=stamp;
      if(!paused&&!media.matches)time+=.006;
      context.clearRect(0,0,width,height);
      const positions=points.map(p=>({x:p.x*width+Math.sin(time+p.phase)*22,y:p.y*height+Math.cos(time*.7+p.phase)*22}));
      for(let i=0;i<positions.length;i++){
        const a=positions[i];
        for(let j=i+1;j<positions.length;j++){
          const b=positions[j],distance=Math.hypot(a.x-b.x,a.y-b.y);
          if(distance>180)continue;
          context.strokeStyle=`rgba(122,171,128,${(1-distance/180)*.2})`;
          context.beginPath();context.moveTo(a.x,a.y);context.lineTo(b.x,b.y);context.stroke();
        }
        context.fillStyle=i%3===0?'rgba(162,251,126,.55)':'rgba(91,166,111,.45)';
        context.beginPath();context.arc(a.x,a.y,i%3===0?1.8:1.1,0,Math.PI*2);context.fill();
      }
      if(!paused&&!media.matches&&!document.hidden)frame=requestAnimationFrame(draw);
    }
    function resize(){
      if(!element||!context)return;
      width=element.clientWidth;height=element.clientHeight;
      const ratio=Math.min(window.devicePixelRatio||1,mobile?1:1.5);
      element.width=width*ratio;element.height=height*ratio;context.setTransform(ratio,0,0,ratio,0,0);
      restart();
    }
    function restart(){cancelAnimationFrame(frame);previous=0;frame=requestAnimationFrame(draw);}
    const observer=new ResizeObserver(resize);observer.observe(element);
    media.addEventListener('change',restart);document.addEventListener('visibilitychange',restart);
    return ()=>{cancelAnimationFrame(frame);observer.disconnect();media.removeEventListener('change',restart);document.removeEventListener('visibilitychange',restart);};
  },[paused]);
  return <><div className={'lab-atmosphere '+(paused?'is-paused':'')} aria-hidden="true"><div className="aurora aurora-violet"/><div className="aurora aurora-cyan"/><div className="atmosphere-grid"/><canvas ref={canvas}/></div><button className="effects-toggle" onClick={()=>setPaused(!paused)} aria-label={paused?'Resume background animations':'Pause background animations'} aria-pressed={paused}>{paused?<Play size={13}/>:<Pause size={13}/>}<span>Ambient motion</span><Sparkles size={12}/></button></>;
});

export function ViewTransition({children,view}:{children:React.ReactNode;view:string}) {
  return <m.div key={view} className="view-transition" initial={{opacity:0,y:12}} animate={{opacity:1,y:0}}>{children}</m.div>;
}

export function DesignTelemetry({rps,replicas,seed,busy}:{rps:number;replicas:number;seed:number;busy:boolean}) {
  return <div className="design-telemetry"><div><span className="telemetry-kicker">EXPERIMENT PARAMETERS</span><span className="telemetry-state"><i/>{busy?'Engine running':'Ready to explore'}</span></div><div className="telemetry-values"><span><strong>{rps.toLocaleString()}</strong><small>offered req / sec</small></span><span><strong>{String(replicas).padStart(2,'0')}</strong><small>application replicas</small></span><span><strong>{seed}</strong><small>reproducible seed</small></span><svg viewBox="0 0 180 50" aria-hidden="true"><defs><linearGradient id="signal"><stop stopColor="#a2f6a1"/><stop offset="1" stopColor="#80df86"/></linearGradient></defs><path d="M0 36H16L24 25L32 34L45 12L55 42L67 23L80 30L94 17L105 29L115 8L127 31L140 21L150 26L163 13L172 22H180" fill="none" stroke="url(#signal)" strokeWidth="2"/></svg></div></div>;
}
