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
    if(params.has('error')){
      clearCallback();
      throw new Error(params.get('error')==='access_denied'
        ?'Google sign-in was canceled. Please try again.'
        :'Google could not finish signing in through Supabase. Check the Supabase Auth logs, then start a new sign-in.');
    }
    const code=params.get('code');
    if(code){
      const {error}=await auth.exchangeCodeForSession(code);
      clearCallback();
      if(error){
        const {data}=await auth.getSession();
        // A retried or already-consumed callback must not hide a valid session.
        if(!data.session)throw new Error(exchangeError(error.code));
      }
    }
    const {data,error}=await auth.getSession();
    if(error)throw new Error('Your sign-in session could not be restored. Please try again.');
    onSession(data.session);
    return ()=>subscription.unsubscribe();
  }catch(error){subscription.unsubscribe();throw error;}
}

function clearCallback(){
  const url=new URL(location.href);
  for(const name of ['code','error','error_code','error_description','sb'])url.searchParams.delete(name);
  // Supabase can include the same callback error in the fragment.
  if(new URLSearchParams(url.hash.slice(1)).has('error'))url.hash='';
  history.replaceState(null,'',url.pathname+url.search+url.hash);
}

function exchangeError(code:string|undefined){
  if(code==='pkce_code_verifier_not_found')return 'This sign-in lost its browser verification. Click Continue with Google again and finish in this same tab; do not copy the callback URL to another tab.';
  if(code==='flow_state_expired'||code==='flow_state_not_found'||code==='invalid_grant')return 'This sign-in link expired or was already used. Click Continue with Google to start a fresh sign-in.';
  if(code==='bad_code_verifier')return 'The sign-in verification does not match. Start Google sign-in again in this tab.';
  return 'Unable to restore your Google session'+(code?' ('+code+').':'.')+' Click Continue with Google to try again.';
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
