-- Private bucket for invoice images/PDFs. No storage policies: only the backend (service_role)
-- uploads and reads files, and the browser gets short-lived signed URLs from the backend.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('invoices', 'invoices', false, 5242880,
        array['image/png', 'image/jpeg', 'image/webp', 'application/pdf'])
on conflict (id) do update set public = false,
  file_size_limit = excluded.file_size_limit, allowed_mime_types = excluded.allowed_mime_types;
