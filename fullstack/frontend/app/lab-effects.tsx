'use client';
import {memo,useEffect,useState} from 'react';
import {LazyMotion,MotionConfig} from 'motion/react';
import * as m from 'motion/react-m';
import {Pause,Play} from 'lucide-react';
const loadAnimations=()=>import('motion/react').then(module=>module.domAnimation);

export function LabMotion({children}:{children:React.ReactNode}){
  return <LazyMotion features={loadAnimations} strict><MotionConfig reducedMotion="user" transition={{duration:.18}}>{children}</MotionConfig></LazyMotion>;
}
// Motion describes request paths, not background decoration. No animation loop
// runs on a page-wide canvas; CSS honours both this control and reduced motion.
export const LabScene=memo(function LabScene(){
  const [paused,setPaused]=useState(false);
  useEffect(()=>{document.documentElement.dataset.flowPaused=String(paused);return()=>{delete document.documentElement.dataset.flowPaused}},[paused]);
  return <button className="effects-toggle" onClick={()=>setPaused(!paused)} aria-label={paused?'Resume flow animation':'Pause flow animation'} aria-pressed={paused}>{paused?<Play size={13}/>:<Pause size={13}/>}<span>Flow motion {paused?'off':'on'}</span></button>;
});
export function ViewTransition({children,view}:{children:React.ReactNode;view:string}){
  return <m.div key={view} className="view-transition" initial={{opacity:0}} animate={{opacity:1}}>{children}</m.div>;
}
