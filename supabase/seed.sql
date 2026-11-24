-- Optional fictional local data. Never run against a shared or production project.
-- Disabled in config.toml. A deliberate session flag is required even locally.
begin;
do $$ begin
  if current_setting('ems.allow_fictional_seed',true) is distinct from 'on' then
    raise exception 'Fictional seed is disabled; enable only in a disposable local project';
  end if;
end $$;
insert into public.invitations(id,email,role) values
  ('10000000-0000-4000-8000-000000000001','fictional-viewer@example.invalid','viewer'),
  ('10000000-0000-4000-8000-000000000002','fictional-editor@example.invalid','editor'),
  ('10000000-0000-4000-8000-000000000003','fictional-admin@example.invalid','admin');
-- No passwords, confirmation tokens, identities, or usable logins are seeded.
insert into auth.users(id,email) values
  ('20000000-0000-4000-8000-000000000001','fictional-viewer@example.invalid'),
  ('20000000-0000-4000-8000-000000000002','fictional-editor@example.invalid'),
  ('20000000-0000-4000-8000-000000000003','fictional-admin@example.invalid');
insert into public.imports(id,original_filename,source_file_hash,storage_path,status,uploaded_by)
values('30000000-0000-4000-8000-000000000001','fictional-example.xlsx',repeat('0',64),
 '30000000-0000-4000-8000-000000000001/source.xlsx','approved','20000000-0000-4000-8000-000000000003');
insert into public.events(id,event_name,event_date,start_time,end_time,location,contact_or_group,
 source_import_id,source_data,fingerprint,match_keys)
values('40000000-0000-4000-8000-000000000001','Fictional Planning Example','2026-11-20','10:00','11:00',
 'Example Hall','Fictional Team','30000000-0000-4000-8000-000000000001','{}','fictional-seed','{}');
insert into public.resource_requests(event_id,resource_description,quantity,source_text,source_data,source_import_id)
values('40000000-0000-4000-8000-000000000001','Fictional folding chairs',12,'12 fictional chairs','{}','30000000-0000-4000-8000-000000000001');
insert into public.calendar_items(event_id,item_type,title,start_at,end_at,is_generated,created_from_import_id)
values('40000000-0000-4000-8000-000000000001','event','Fictional Planning Example','2026-11-20T10:00:00-07:00',
 '2026-11-20T11:00:00-07:00',true,'30000000-0000-4000-8000-000000000001');
commit;
