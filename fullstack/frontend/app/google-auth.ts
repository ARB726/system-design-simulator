import { createClient, type Session, type SupabaseClient } from '@supabase/supabase-js';
import type { Settings } from './lab-types';

let client:SupabaseClient|undefined;
let project='';
function authClient(settings:Settings){
  const {supabase_url:url,supabase_publishable_key:key}=settings;
  if(!url||!key)throw new Error('Google sign-in is not configured for this workspace.');
  const identity=url+'|'+key;
  if(!client||identity!==project){
    client=createClient(url,key,{auth:{flowType:'pkce',storage:window.sessionStorage,
      persistSession:true,autoRefreshToken:true,detectSessionInUrl:false}});
    project=identity;
  }
  return client;
}

export async function connectGoogleSession(settings:Settings,onSession:(session:Session|null)=>void){
  const auth=authClient(settings).auth;
  const {data:{subscription}}=auth.onAuthStateChange((_event,session)=>onSession(session));
  try{
    const params=new URLSearchParams(location.search);
    if(params.has('error'))throw new Error('Google sign-in was canceled or unavailable. Please try again.');
    const code=params.get('code');
    if(code){
      const {error}=await auth.exchangeCodeForSession(code);
      if(error)throw new Error('Unable to finish Google sign-in. Please try again.');
      history.replaceState(null,'',location.pathname);
    }
    const {data,error}=await auth.getSession();
    if(error)throw new Error('Your sign-in session could not be restored. Please try again.');
    onSession(data.session);
    return ()=>subscription.unsubscribe();
  }catch(error){subscription.unsubscribe();throw error;}
}

export async function signInGoogle(settings:Settings){
  const {error}=await authClient(settings).auth.signInWithOAuth({provider:'google',
    options:{redirectTo:location.origin+'/'}});
  if(error)throw new Error('Google sign-in could not start. Please try again.');
}

export async function signOutGoogle(settings:Settings){
  const {error}=await authClient(settings).auth.signOut({scope:'local'});
  if(error)throw new Error('Sign-out could not finish. Please try again.');
}
