// Infrastructure only: the application remains Python/FastAPI.
// Link and verify the user-selected DEVELOPMENT branch before `neon deploy`.
import { defineConfig } from '@neon/config/v1';

export default defineConfig({
  auth: true,
  buckets: {
    uploads: { access: 'private' },
  },
});
