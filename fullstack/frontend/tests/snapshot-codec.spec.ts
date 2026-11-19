import {test,expect} from '@playwright/test';
import fixture from '../public/guest-demo.json';
import type {Job} from '../app/lab-types';
import {encodeSnapshot,decodeSnapshot} from '../app/snapshot-codec';

test('shared snapshots preserve evidence and exclude identity and unrelated data',async()=>{
  const job={...fixture.experiments[0],id:'private-owner-id',token:'secret-token',owner:'owner@example.com'} as unknown as Job;
  const hash=await encodeSnapshot(job);
  const shared=await decodeSnapshot(hash);
  expect(shared.id).toBe('shared-snapshot');
  expect(shared.payload.config).toEqual(job.payload.config);
  expect(shared.result?.summary?.p95_ms).toBe(job.result?.summary?.p95_ms);
  expect(JSON.stringify(shared)).not.toMatch(/private-owner-id|secret-token|owner@example.com/);
  expect(hash.length).toBeLessThan(16000);
});

test('invalid, oversized and unfinished snapshots are rejected',async()=>{
  await expect(decodeSnapshot('#share=v2.invalid')).rejects.toThrow();
  await expect(decodeSnapshot('#share=v1.'+'a'.repeat(16001))).rejects.toThrow();
  await expect(encodeSnapshot({...fixture.experiments[0],status:'running'} as unknown as Job)).rejects.toThrow();
  const bad=structuredClone(fixture.experiments[0]) as unknown as Job;
  bad.result!.summary!.p95_ms=NaN;
  await expect(encodeSnapshot(bad)).rejects.toThrow();
});
