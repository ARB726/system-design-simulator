import {test,expect,type Page} from '@playwright/test';

const project='https://project.supabase.co';
const user={id:'c6d607e2-730d-46ab-8058-088b488542a1',email:'google-user@example.com',app_metadata:{provider:'google'},user_metadata:{},aud:'authenticated'};
const token=[{alg:'ES256',typ:'JWT'},{sub:user.id,aud:'authenticated',role:'authenticated',exp:Math.floor(Date.now()/1000)+3600,iat:Math.floor(Date.now()/1000),iss:project+'/auth/v1'},'signature'].map(v=>Buffer.from(typeof v==='string'?v:JSON.stringify(v)).toString('base64url')).join('.');
const session={access_token:token,refresh_token:'mock-refresh-token',expires_in:3600,expires_at:Math.floor(Date.now()/1000)+3600,token_type:'bearer',user};

async function settings(page:Page){
  await page.route('**/api/settings',r=>r.fulfill({json:{auth:'supabase',supabase_url:project,supabase_publishable_key:'sb_publishable_public_test_key',ai_enabled:true,ai_provider:'gemini'}}));
  await page.route('**/api/catalog',r=>r.fulfill({json:{presets:[],challenges:[]}}));
}

test('Google button starts PKCE sign-in without password fields',async({page})=>{
  await settings(page);
  await page.route(project+'/auth/v1/authorize**',r=>r.fulfill({contentType:'text/html',body:'Google sign-in test provider'}));
  await page.goto('/');
  await page.getByRole('button',{name:'Run simulation',exact:true}).click();
  const dialog=page.getByRole('dialog');
  await expect(dialog.getByRole('button',{name:'Continue with Google'})).toBeVisible();
  await expect(dialog.getByLabel('Password',{exact:true})).toHaveCount(0);
  await dialog.getByRole('button',{name:'Continue with Google'}).click();
  await page.waitForURL(project+'/auth/v1/authorize**');
  const url=new URL(page.url());
  expect(url.searchParams.get('provider')).toBe('google');
  expect(url.searchParams.get('code_challenge_method')).toBe('s256');
  expect(url.searchParams.get('code_challenge')).toBeTruthy();
  expect(url.searchParams.get('redirect_to')).toBe('http://127.0.0.1:8080/');
});

test('Google callback exchanges code, uses user token, and clears private state on sign-out',async({page})=>{
  await settings(page);
  await page.addInitScript(()=>sessionStorage.setItem('sb-project-auth-token-code-verifier',JSON.stringify('test-verifier')));
  let authenticated=0;
  await page.route(project+'/auth/v1/token**',async route=>{
    const body=route.request().postDataJSON();
    expect(body.auth_code).toBe('test-code');
    expect(body.code_verifier).toBe('test-verifier');
    await route.fulfill({json:session});
  });
  await page.route('**/api/experiments',route=>{
    expect(route.request().headers().authorization).toBe('Bearer '+token);authenticated++;
    return route.fulfill({json:[]});
  });
  await page.route(project+'/auth/v1/logout**',r=>r.fulfill({status:204}));
  await page.goto('/?code=test-code');
  await expect(page.getByRole('button',{name:/google-user@example.com/})).toBeVisible();
  await expect.poll(()=>authenticated).toBeGreaterThan(0);
  expect(new URL(page.url()).search).toBe('');
  expect(await page.evaluate(()=>localStorage.getItem('sb-project-auth-token'))).toBeNull();
  await page.getByRole('button',{name:/google-user@example.com/}).click();
  await expect(page.getByText('google-user@example.com',{exact:true})).toHaveCount(0);
  await page.getByRole('button',{name:'Experiment library',exact:true}).click();
  await expect(page.getByRole('button',{name:'Sign in',exact:true})).toBeVisible();
});

test('provider callback error leaves the user signed out',async({page})=>{
  await settings(page);
  await page.goto('/?error=access_denied');
  await expect(page.getByRole('alert').filter({hasText:/Google sign-in was canceled/})).toBeVisible();
  await page.getByRole('button',{name:'Experiment library',exact:true}).click();
  await expect(page.getByRole('button',{name:'Sign in',exact:true})).toBeVisible();
});

test('missing PKCE verifier explains recovery and removes the unusable callback',async({page})=>{
  await settings(page);
  await page.goto('/?code=orphaned-code');
  await expect(page.getByRole('alert').filter({hasText:/lost its browser verification/})).toBeVisible();
  expect(new URL(page.url()).search).toBe('');
  await page.reload();
  await expect(page.getByRole('heading',{name:'Find the constraint.'})).toBeVisible();
  await expect(page.getByRole('alert').filter({hasText:/Could not connect/})).toHaveCount(0);
});

test('an already consumed callback preserves an existing session',async({page})=>{
  await settings(page);
  await page.addInitScript(value=>sessionStorage.setItem('sb-project-auth-token',JSON.stringify(value)),session);
  await page.route('**/api/experiments',r=>r.fulfill({json:[]}));
  await page.goto('/?code=already-used-code');
  await expect(page.getByRole('button',{name:/google-user@example.com/})).toBeVisible();
  await expect(page.getByRole('alert').filter({hasText:/Could not connect/})).toHaveCount(0);
  expect(new URL(page.url()).search).toBe('');
});
