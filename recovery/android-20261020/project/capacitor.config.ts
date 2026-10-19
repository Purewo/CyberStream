import type { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
  appId: 'com.purewo.cyberstream',
  appName: 'CyberStream',
  webDir: 'dist',
  server: {
    // Verified against pioneer.fan:884 on 2026-10-20. The old hosted-beta
    // origin is no longer in that server's CORS allow-list.
    hostname: 'localhost',
    androidScheme: 'https',
  },
  plugins: {
    // The production web client already exercises this CORS/cookie path. Keep
    // this compatibility build on Chromium rather than HttpURLConnection so
    // its DNS/TLS behavior matches the working mobile website.
    CapacitorHttp: {
      enabled: false,
    },
  },
};

export default config;
