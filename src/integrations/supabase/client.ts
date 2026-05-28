import { createClient } from "@supabase/supabase-js";

// Public/publishable values — safe to ship in client bundle.
const SUPABASE_URL = "https://lkwmpjdojkhysveneubo.supabase.co";
const SUPABASE_ANON_KEY =
  "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imxrd21wamRvamtoeXN2ZW5ldWJvIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzk3MDE2NDAsImV4cCI6MjA5NTI3NzY0MH0.2fe3CuUmwE-JlRCScUqCzw-LYbHKhkCV0b7Y8FsbchA";

export const supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
  auth: {
    persistSession: true,
    autoRefreshToken: true,
    detectSessionInUrl: true,
  },
});
