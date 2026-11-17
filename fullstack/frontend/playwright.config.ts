import { defineConfig } from '@playwright/test';
export default defineConfig({testDir:'./tests',timeout:90000,use:{baseURL:'http://127.0.0.1:8080',headless:true,channel:process.env.PLAYWRIGHT_CHANNEL||'chrome'},workers:1,reporter:'list'});
