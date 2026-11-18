import type { Metadata } from 'next';
import './globals.css';
import './immersive.css';
import './ai.css';
import './topology.css';
export const metadata: Metadata = { title: 'Systems Lab — Design. Stress. Understand.', description: 'An interactive system design laboratory. Build an architecture, inject failures, and understand the tradeoffs.' };
export default function Layout({ children }: Readonly<{children: React.ReactNode}>) { return <html lang="en"><body>{children}</body></html>; }
