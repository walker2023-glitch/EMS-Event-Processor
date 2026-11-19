-- EMS shared-workspace backend. Apply with Supabase CLI migrations, never ad hoc app DDL.
begin;
create extension if not exists pgcrypto;

create table public.profiles (
  id uuid primary key references auth.users(id), display_name text not null default '',
  email text not null, role text not null check (role in ('viewer','editor','admin')),
  is_active boolean not null default false,
  created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create unique index profiles_email on public.profiles(lower(email));
create table public.invitations (
  id uuid primary key default gen_random_uuid(), email text not null,
  role text not null check (role in ('viewer','editor','admin')),
  created_by uuid references public.profiles(id),
  expires_at timestamptz not null default now() + interval '7 days',
  accepted_at timestamptz, revoked_at timestamptz,
  created_at timestamptz not null default now()
);
create unique index invitations_pending_email on public.invitations(lower(email))
  where accepted_at is null and revoked_at is null;
create table public.imports (
  id uuid primary key default gen_random_uuid(), original_filename text not null,
  source_file_hash text not null unique check (source_file_hash ~ '^[a-f0-9]{64}$'),
  storage_path text not null unique, status text not null default 'uploaded'
    check (status in ('uploaded','processing','preview_ready','approved','failed')),
  uploaded_by uuid not null references public.profiles(id), uploaded_at timestamptz not null default now(),
  approved_by uuid references public.profiles(id), approved_at timestamptz,
  error_summary text, payload jsonb not null default '{}', result jsonb,
  expires_at timestamptz not null default now() + interval '1 year',
  created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create table public.events (
  id uuid primary key default gen_random_uuid(), source_request_id text, source_reservation_id text,
  event_name text, event_date date, start_time time, end_time time, location text, contact_or_group text,
  source_import_id uuid not null references public.imports(id), source_sheet text,
  source_row integer, source_page integer, original_request_text text, data_quality_status text,
  planning_status text not null default 'Not reviewed'
    check (planning_status in ('Not reviewed','In progress','Ready','Complete','On hold')),
  planning_notes text not null default '', recommendations text not null default '',
  source_data jsonb not null, fingerprint text not null, match_keys text[] not null,
  created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create index events_date on public.events(event_date);
create index events_location on public.events(location);
create index events_status on public.events(planning_status, data_quality_status);
create index events_request on public.events(source_request_id,event_date);
create index events_reservation on public.events(source_reservation_id,event_date);
create index events_matching on public.events using gin(match_keys);
create index events_import on public.events(source_import_id);
create table public.import_events (
  import_id uuid not null references public.imports(id), candidate_id text not null,
  event_id uuid not null references public.events(id), decision text not null,
  created_at timestamptz not null default now(), primary key(import_id,candidate_id)
);
create index import_events_event on public.import_events(event_id);
create table public.resource_requests (
  id uuid primary key default gen_random_uuid(), event_id uuid not null references public.events(id),
  resource_description text, resource_category text, quantity numeric,
  source_text text, source_data jsonb not null, source_import_id uuid not null references public.imports(id),
  is_current boolean not null default true,
  created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create index resources_event on public.resource_requests(event_id,is_current);
create index resources_import on public.resource_requests(source_import_id);
create table public.issues (
  id uuid primary key default gen_random_uuid(), import_id uuid not null references public.imports(id),
  event_id uuid references public.events(id), issue_type text, severity text, message text,
  source_sheet text, source_row integer, source_data jsonb not null,
  resolved boolean not null default false, resolved_by uuid references public.profiles(id), resolved_at timestamptz,
  created_at timestamptz not null default now()
);
create index issues_import on public.issues(import_id);
create index issues_event on public.issues(event_id);
create index issues_review on public.issues(resolved,severity);
create table public.calendar_items (
  id uuid primary key default gen_random_uuid(), event_id uuid not null references public.events(id),
  item_type text not null check (item_type in ('event','setup','teardown','planning_meeting','resource_task','follow_up')),
  title text not null, start_at timestamptz, end_at timestamptz, all_day boolean not null default false,
  location text, description text, status text not null default 'Not reviewed'
    check (status in ('Not reviewed','In progress','Ready','Complete','On hold')),
  is_generated boolean not null default false, user_modified boolean not null default false,
  created_from_import_id uuid references public.imports(id),
  created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
  check (end_at is null or (start_at is not null and end_at >= start_at))
);
create unique index calendar_generated on public.calendar_items(event_id,item_type) where is_generated;
create index calendar_times on public.calendar_items(start_at,end_at);
create index calendar_filters on public.calendar_items(item_type,status,location);
create index calendar_import on public.calendar_items(created_from_import_id);
create table public.export_files (
  id uuid primary key default gen_random_uuid(), import_id uuid not null references public.imports(id),
  file_type text not null check (file_type in ('organized_workbook','issues_workbook')),
  storage_path text not null unique, filename text not null,
  created_at timestamptz not null default now(), expires_at timestamptz not null default now() + interval '1 year',
  unique(import_id,file_type)
);

-- All SECURITY DEFINER entry points have a fixed search_path and authorize auth.uid().
create function public.ems_role() returns text language sql stable security definer set search_path = '' as $$
  select p.role from public.profiles p join auth.users u on u.id=p.id
  where p.id=auth.uid() and p.is_active and u.email_confirmed_at is not null
$$;
create function public.ems_require(p_roles text[]) returns void language plpgsql stable security definer set search_path = '' as $$
begin
  if not coalesce(public.ems_role()=any(p_roles),false) then
    raise insufficient_privilege using message='Account permission required';
  end if;
end $$;
create function public.ems_normalize(p_text text) returns text language sql immutable set search_path = '' as $$
  select lower(regexp_replace(btrim(coalesce(p_text,'')), '\s+', ' ', 'g'))
$$;

create function public.invited_profile() returns trigger language plpgsql security definer set search_path = '' as $$
declare invitation public.invitations;
begin
  select * into invitation from public.invitations where lower(email)=lower(new.email)
    and accepted_at is null and revoked_at is null and expires_at>now() for update;
  if invitation.id is null then raise insufficient_privilege using message='Invitation required'; end if;
  insert into public.profiles(id,email,role,is_active) values(new.id,lower(new.email),invitation.role,false);
  return new;
end $$;
create trigger ems_invited_profile after insert on auth.users for each row execute function public.invited_profile();

create function public.begin_invitation(p_email text,p_role text) returns jsonb language plpgsql security definer set search_path = '' as $$
declare invitation public.invitations;
begin
  perform public.ems_require(array['admin']);
  if p_role not in ('viewer','editor','admin') or p_email !~ '^[^\s@]+@[^\s@]+\.[^\s@]+$' or length(p_email)>254 then
    raise invalid_parameter_value using message='Invalid invitation';
  end if;
  if exists(select from public.profiles where lower(email)=lower(p_email)) then
    raise exception 'An account already exists' using errcode='40001';
  end if;
  update public.invitations set revoked_at=now() where lower(email)=lower(p_email)
    and accepted_at is null and revoked_at is null and expires_at<=now();
  insert into public.invitations(email,role,created_by) values(lower(p_email),p_role,auth.uid()) returning * into invitation;
  return to_jsonb(invitation);
end $$;
create function public.revoke_invitation(p_id uuid) returns jsonb language plpgsql security definer set search_path = '' as $$
begin
  perform public.ems_require(array['admin']);
  update public.invitations set revoked_at=now() where id=p_id and accepted_at is null;
  if not found then raise no_data_found; end if;
  return jsonb_build_object('id',p_id,'revoked',true);
end $$;
create function public.accept_invitation() returns jsonb language plpgsql security definer set search_path = '' as $$
declare invitation public.invitations; account auth.users; profile public.profiles;
begin
  select * into account from auth.users where id=auth.uid();
  if account.id is null or account.email_confirmed_at is null then raise insufficient_privilege; end if;
  select * into profile from public.profiles where id=account.id;
  if profile.is_active then return to_jsonb(profile); end if;
  select * into invitation from public.invitations where lower(email)=lower(account.email)
    and accepted_at is null and revoked_at is null and expires_at>now() for update;
  if invitation.id is null then raise insufficient_privilege; end if;
  update public.invitations set accepted_at=now() where id=invitation.id;
  update public.profiles set is_active=true, role=invitation.role, updated_at=now() where id=account.id returning * into profile;
  return to_jsonb(profile);
end $$;
create function public.set_profile_role(p_user uuid,p_role text,p_active boolean) returns jsonb language plpgsql security definer set search_path = '' as $$
declare profile public.profiles;
begin
  perform public.ems_require(array['admin']);
  perform pg_advisory_xact_lock(19471119);
  if p_role not in ('viewer','editor','admin') or p_active is null then raise invalid_parameter_value; end if;
  if exists(select from public.profiles where id=p_user and role='admin' and is_active)
      and (p_role<>'admin' or not p_active)
      and (select count(*) from public.profiles where role='admin' and is_active)=1 then
    raise exception 'Cannot deactivate the last administrator' using errcode='40001';
  end if;
  update public.profiles set role=p_role,is_active=p_active,updated_at=now() where id=p_user returning * into profile;
  if not found then raise no_data_found; end if;
  return to_jsonb(profile);
end $$;

create function public.register_import(p_filename text,p_hash text) returns jsonb language plpgsql security definer set search_path = '' as $$
declare record public.imports; identifier uuid=gen_random_uuid();
begin
  perform public.ems_require(array['admin']);
  if length(p_filename)>180 or p_filename !~* '\.(xls|xlsx)$' then raise invalid_parameter_value; end if;
  insert into public.imports(id,original_filename,source_file_hash,storage_path,uploaded_by)
    values(identifier,p_filename,p_hash,identifier::text || '/source.' || lower(substring(p_filename from '[^.]+$')),auth.uid())
    on conflict(source_file_hash) do nothing;
  select * into record from public.imports where source_file_hash=p_hash;
  return to_jsonb(record)-'payload';
end $$;
create function public.claim_import(p_id uuid) returns jsonb language plpgsql security definer set search_path = '' as $$
begin
  perform public.ems_require(array['admin']);
  update public.imports set status='processing',updated_at=now(),error_summary=null where id=p_id and status in ('uploaded','failed');
  if not found then raise exception 'Import already being processed' using errcode='40001'; end if;
  return jsonb_build_object('id',p_id,'status','processing');
end $$;
create function public.fail_import(p_id uuid) returns jsonb language plpgsql security definer set search_path = '' as $$
begin
  perform public.ems_require(array['admin']);
  update public.imports set status='failed',updated_at=now(),error_summary='Processing failed. Check the workbook and retry.' where id=p_id and status='processing';
  return jsonb_build_object('id',p_id,'status','failed');
end $$;
create function public.finish_import(p_id uuid,p_payload jsonb,p_exports jsonb) returns jsonb language plpgsql security definer set search_path = '' as $$
declare record public.imports; export jsonb;
begin
  perform public.ems_require(array['admin']);
  select * into record from public.imports where id=p_id for update;
  if record.status is distinct from 'processing' then raise exception 'Invalid state' using errcode='40001'; end if;
  if jsonb_typeof(p_payload->'candidates') is distinct from 'array'
      or jsonb_array_length(p_payload->'candidates')>2000
      or jsonb_typeof(p_payload->'issues') is distinct from 'array'
      or not exists(select from jsonb_array_elements(p_exports) x where x->>'file_type'='organized_workbook') then
    raise invalid_parameter_value;
  end if;
  if (select count(*) from jsonb_array_elements(p_payload->'candidates')) <>
      (select count(distinct x->>'candidate_id') from jsonb_array_elements(p_payload->'candidates') x) then
    raise invalid_parameter_value;
  end if;
  for export in select * from jsonb_array_elements(p_exports) loop
    if export->>'storage_path' not like p_id::text || '/exports/%' then raise invalid_parameter_value; end if;
    insert into public.export_files(import_id,file_type,storage_path,filename)
      values(p_id,export->>'file_type',export->>'storage_path',export->>'filename');
  end loop;
  update public.imports set status='preview_ready',payload=p_payload,updated_at=now() where id=p_id returning * into record;
  return to_jsonb(record)-'payload';
end $$;

create function public.preview_import(p_id uuid) returns jsonb language plpgsql security definer set search_path = '' as $$
declare record public.imports; candidate jsonb; key text; matches uuid[]; potential uuid[];
  classification text; collision boolean; same boolean; snapshot jsonb; items jsonb='[]'; counts jsonb; result jsonb;
begin
  perform public.ems_require(array['admin']);
  select * into record from public.imports where id=p_id;
  if not found then raise no_data_found; end if;
  if record.status not in ('preview_ready','approved') then raise exception 'Preview not ready' using errcode='40001'; end if;
  for candidate in select * from jsonb_array_elements(record.payload->'candidates') loop
    matches='{}'; potential='{}'; snapshot='[]';
    for key in select jsonb_array_elements_text(candidate->'match_keys') loop
      select coalesce(array_agg(id order by id),'{}') into matches from public.events where match_keys @> array[key];
      exit when cardinality(matches)>0;
    end loop;
    select count(*)>1 into collision from jsonb_array_elements(record.payload->'candidates') c
      where c->'match_keys'->>0 is not null and c->'match_keys'->>0=candidate->'match_keys'->>0;
    select coalesce(array_agg(id order by id),'{}') into potential from public.events
      where event_date=(candidate->'source'->>'event_date')::date
        and public.ems_normalize(event_name)=public.ems_normalize(candidate->'source'->>'event_name');
    if cardinality(matches)=1 and not collision then
      select fingerprint=candidate->>'fingerprint' into same from public.events where id=matches[1];
      classification=case when same then 'unchanged' else 'changed' end;
    elsif cardinality(matches)=0 and cardinality(potential)=0 and not collision
        and jsonb_array_length(candidate->'match_keys')>0 then classification='new';
    else classification='possible_duplicate'; end if;
    select coalesce(jsonb_agg(jsonb_build_object('id',id,'fingerprint',fingerprint) order by id),'[]') into snapshot
      from public.events where id=any(matches || potential);
    items=items || jsonb_build_array(jsonb_build_object('candidate',candidate,'classification',classification,
      'matched_event_id',case when cardinality(matches)=1 then matches[1] else null end,
      'possible_matches',(select coalesce(jsonb_agg(distinct x),'[]') from unnest(matches || potential) x),
      'existing_snapshot',snapshot,'within_file_collision',collision));
  end loop;
  select jsonb_object_agg(kind,amount) into counts from (
    select kind,(select count(*) from jsonb_array_elements(items) x where x->>'classification'=kind) amount
      from unnest(array['new','changed','unchanged','possible_duplicate']) kind) t;
  result=jsonb_build_object('import_id',p_id,'items',items,'issues',record.payload->'issues',
    'counts',counts,'processing_counts',record.payload->'counts');
  return result || jsonb_build_object('preview_version',md5(result::text));
end $$;

create function public.approve_import(p_id uuid,p_version text,p_resolutions jsonb default '[]') returns jsonb language plpgsql security definer set search_path = '' as $$
declare record public.imports; preview jsonb; item jsonb; candidate jsonb; resolution jsonb;
  source jsonb; resource jsonb; cal jsonb; issue jsonb; event_uuid uuid;
  decision text; prior public.events; link_count integer=0;
begin
  perform public.ems_require(array['admin']);
  -- Serialize approval/matching across imports; each call is one PostgreSQL transaction.
  perform pg_advisory_xact_lock(19471120);
  select * into record from public.imports where id=p_id for update;
  if not found then raise no_data_found; end if;
  if record.status='approved' then return record.result; end if;
  preview=public.preview_import(p_id);
  if preview->>'preview_version' is distinct from p_version then raise exception 'Stale preview' using errcode='40001'; end if;
  if jsonb_typeof(p_resolutions) is distinct from 'array' then raise invalid_parameter_value; end if;
  if (select count(*) from jsonb_array_elements(p_resolutions)) <>
      (select count(distinct x->>'candidate_id') from jsonb_array_elements(p_resolutions) x) then raise invalid_parameter_value; end if;
  for resolution in select * from jsonb_array_elements(p_resolutions) loop
    if not exists(select from jsonb_array_elements(preview->'items') x
      where x->'candidate'->>'candidate_id'=resolution->>'candidate_id' and x->>'classification'='possible_duplicate') then
      raise invalid_parameter_value;
    end if;
  end loop;
  for item in select * from jsonb_array_elements(preview->'items') loop
    candidate=item->'candidate'; source=candidate->'source'; resolution=null;
    decision=item->>'classification'; event_uuid=(item->>'matched_event_id')::uuid;
    if decision='possible_duplicate' then
      select x into resolution from jsonb_array_elements(p_resolutions) x where x->>'candidate_id'=candidate->>'candidate_id';
      if resolution is null or resolution->>'action' not in ('create','match','skip') then
        raise exception 'Explicit duplicate resolution required' using errcode='40001';
      end if;
      if resolution->>'action'='skip' then continue; end if;
      if resolution->>'action'='create' then event_uuid=null;
      else
        event_uuid=(resolution->>'event_id')::uuid;
        if not (item->'possible_matches' @> jsonb_build_array(event_uuid)) then raise invalid_parameter_value; end if;
      end if;
    end if;
    -- Never let two source occurrences silently overwrite one another in a batch.
    if event_uuid is not null and exists(select from public.import_events where import_id=p_id and event_id=event_uuid) then
      raise exception 'Two candidates target the same event; preserve both or skip' using errcode='40001';
    end if;
    prior=null;
    if event_uuid is not null then select * into prior from public.events where id=event_uuid for update; end if;
    if event_uuid is null then event_uuid=gen_random_uuid(); end if;
    insert into public.events(id,source_request_id,source_reservation_id,event_name,event_date,start_time,end_time,location,contact_or_group,
      source_import_id,source_sheet,source_row,source_page,original_request_text,data_quality_status,source_data,fingerprint,match_keys)
    values(event_uuid,source->>'source_request_id',source->>'source_reservation_id',source->>'event_name',(source->>'event_date')::date,
      (source->>'start_time')::time,(source->>'end_time')::time,source->>'location',source->>'contact_or_group',p_id,
      source->>'source_sheet',(source->>'source_row')::int,(source->>'source_page')::int,source->>'original_request_text',
      source->>'data_quality_status',source,candidate->>'fingerprint',array(select jsonb_array_elements_text(candidate->'match_keys')))
    on conflict(id) do update set source_request_id=excluded.source_request_id,source_reservation_id=excluded.source_reservation_id,
      event_name=excluded.event_name,event_date=excluded.event_date,start_time=excluded.start_time,end_time=excluded.end_time,
      location=excluded.location,contact_or_group=excluded.contact_or_group,source_import_id=p_id,source_sheet=excluded.source_sheet,
      source_row=excluded.source_row,source_page=excluded.source_page,original_request_text=excluded.original_request_text,
      data_quality_status=excluded.data_quality_status,source_data=excluded.source_data,fingerprint=excluded.fingerprint,
      match_keys=excluded.match_keys,updated_at=now();
    if prior.id is null or prior.fingerprint is distinct from candidate->>'fingerprint' then
      update public.resource_requests set is_current=false,updated_at=now() where event_id=event_uuid and is_current;
      for resource in select * from jsonb_array_elements(candidate->'resources') loop
        insert into public.resource_requests(event_id,resource_description,resource_category,quantity,source_text,source_data,source_import_id)
        values(event_uuid,resource->>'resource_description',resource->>'resource_category',(resource->>'quantity')::numeric,
          resource->>'source_text',resource->'source_data',p_id);
      end loop;
    end if;
    insert into public.import_events(import_id,candidate_id,event_id,decision) values(p_id,candidate->>'candidate_id',event_uuid,coalesce(resolution->>'action',decision));
    if decision='possible_duplicate' then
      insert into public.issues(import_id,event_id,issue_type,severity,message,source_sheet,source_row,source_data)
      values(p_id,event_uuid,'Possible duplicate','warning','Ambiguous matching required an explicit import decision.',
        source->>'source_sheet',(source->>'source_row')::int,jsonb_build_object('candidate',candidate,'decision',resolution));
    end if;
    for cal in select * from jsonb_array_elements(candidate->'calendar') loop
      insert into public.calendar_items(event_id,item_type,title,start_at,end_at,all_day,location,description,is_generated,created_from_import_id)
      values(event_uuid,cal->>'item_type',cal->>'title',(cal->>'start_at')::timestamptz,(cal->>'end_at')::timestamptz,
        (cal->>'all_day')::boolean,cal->>'location',cal->>'description',true,p_id)
      on conflict(event_id,item_type) where is_generated do update set
        title=case when public.calendar_items.user_modified then public.calendar_items.title else excluded.title end,
        start_at=case when public.calendar_items.user_modified then public.calendar_items.start_at else excluded.start_at end,
        end_at=case when public.calendar_items.user_modified then public.calendar_items.end_at else excluded.end_at end,
        all_day=case when public.calendar_items.user_modified then public.calendar_items.all_day else excluded.all_day end,
        location=case when public.calendar_items.user_modified then public.calendar_items.location else excluded.location end,
        description=case when public.calendar_items.user_modified then public.calendar_items.description else excluded.description end,
        created_from_import_id=p_id,updated_at=now();
    end loop;
    link_count=link_count+1;
  end loop;
  for issue in select * from jsonb_array_elements(record.payload->'issues') loop
    select event_id into event_uuid from public.import_events where import_id=p_id and candidate_id=issue->>'Related Event ID';
    insert into public.issues(import_id,event_id,issue_type,severity,message,source_sheet,source_row,source_data)
    values(p_id,event_uuid,issue->>'Issue Type',issue->>'Severity',issue->>'Description',issue->>'Source Sheet',(issue->>'Source Row')::int,issue);
  end loop;
  update public.imports set status='approved',approved_by=auth.uid(),approved_at=now(),updated_at=now(),
    result=jsonb_build_object('import_id',p_id,'status','approved','events_applied',link_count) where id=p_id returning * into record;
  return record.result;
end $$;

create function public.update_planning(p_id uuid,p_patch jsonb) returns jsonb language plpgsql security definer set search_path = '' as $$
declare record public.events;
begin
  perform public.ems_require(array['editor','admin']);
  if exists(select from jsonb_object_keys(p_patch) k where k not in ('planning_notes','planning_status','recommendations'))
      or p_patch='{}' or exists(select from jsonb_each(p_patch) x where jsonb_typeof(x.value)<>'string')
      or length(coalesce(p_patch->>'planning_notes',''))>20000 or length(coalesce(p_patch->>'recommendations',''))>20000 then raise invalid_parameter_value; end if;
  update public.events set planning_notes=coalesce(p_patch->>'planning_notes',planning_notes),
    planning_status=coalesce(p_patch->>'planning_status',planning_status), recommendations=coalesce(p_patch->>'recommendations',recommendations),updated_at=now()
    where id=p_id returning * into record;
  if not found then raise no_data_found; end if;
  return to_jsonb(record);
end $$;
create function public.resolve_issue(p_id uuid,p_resolved boolean) returns jsonb language plpgsql security definer set search_path = '' as $$
declare record public.issues;
begin
  perform public.ems_require(array['admin']);
  update public.issues set resolved=p_resolved,resolved_by=case when p_resolved then auth.uid() end,
    resolved_at=case when p_resolved then now() end where id=p_id returning * into record;
  if not found then raise no_data_found; end if;
  return to_jsonb(record);
end $$;
create function public.save_calendar(p_id uuid,p_data jsonb) returns jsonb language plpgsql security definer set search_path = '' as $$
declare record public.calendar_items;
begin
  perform public.ems_require(array['editor','admin']);
  if exists(select from jsonb_object_keys(p_data) k where k not in ('event_id','item_type','title','start_at','end_at','all_day','location','description','status'))
      or length(p_data->>'title') not between 1 and 300 or length(p_data->>'description')>20000
      or length(p_data->>'location')>1000 or p_data->>'start_at' is null then raise invalid_parameter_value; end if;
  if p_id is null then
    insert into public.calendar_items(event_id,item_type,title,start_at,end_at,all_day,location,description,status,user_modified)
    values((p_data->>'event_id')::uuid,p_data->>'item_type',p_data->>'title',(p_data->>'start_at')::timestamptz,
      (p_data->>'end_at')::timestamptz,coalesce((p_data->>'all_day')::boolean,false),p_data->>'location',p_data->>'description',p_data->>'status',true)
      returning * into record;
  else
    update public.calendar_items set title=p_data->>'title',start_at=(p_data->>'start_at')::timestamptz,
      end_at=(p_data->>'end_at')::timestamptz,all_day=coalesce((p_data->>'all_day')::boolean,false),location=p_data->>'location',
      description=p_data->>'description',status=p_data->>'status',user_modified=true,updated_at=now()
      where id=p_id and event_id=(p_data->>'event_id')::uuid and item_type=p_data->>'item_type' returning * into record;
    if not found then raise no_data_found; end if;
  end if;
  return to_jsonb(record);
end $$;
create function public.query_calendar(p_filters jsonb default '{}',p_limit integer default 50,p_offset integer default 0)
returns jsonb language plpgsql stable security invoker set search_path = '' as $$
declare result jsonb;
begin
  perform public.ems_require(array['viewer','editor','admin']);
  if p_limit not between 1 and 100 or p_offset not between 0 and 100000 then raise invalid_parameter_value; end if;
  with filtered as (
    select c.* from public.calendar_items c join public.events e on e.id=c.event_id where
      (p_filters->>'date_from' is null or coalesce(c.end_at,c.start_at) at time zone coalesce(p_filters->>'timezone','UTC') >= (p_filters->>'date_from')::date)
      and (p_filters->>'date_to' is null or c.start_at at time zone coalesce(p_filters->>'timezone','UTC') < (p_filters->>'date_to')::date+1)
      and (p_filters->>'event_name' is null or position(public.ems_normalize(p_filters->>'event_name') in public.ems_normalize(e.event_name))>0)
      and (p_filters->>'location' is null or c.location=p_filters->>'location')
      and (p_filters->>'item_type' is null or c.item_type=p_filters->>'item_type')
      and (p_filters->>'planning_status' is null or e.planning_status=p_filters->>'planning_status')
      and (p_filters->>'data_quality_status' is null or e.data_quality_status=p_filters->>'data_quality_status')
      and (p_filters->>'import_id' is null or exists(select from public.import_events ie where ie.event_id=e.id and ie.import_id=(p_filters->>'import_id')::uuid))
  ), page as (select * from filtered order by start_at nulls last,id limit p_limit offset p_offset)
  select jsonb_build_object('items',coalesce((select jsonb_agg(to_jsonb(p)) from page p),'[]'),
    'total',(select count(*) from filtered),'limit',p_limit,'offset',p_offset) into result;
  return result;
end $$;

-- No direct writes, even for admins. Narrow RPCs protect source-owned fields and atomicity.
revoke all on public.profiles,public.invitations,public.imports,public.events,public.import_events,
  public.resource_requests,public.issues,public.calendar_items,public.export_files from anon,authenticated;
grant select on public.profiles,public.invitations,public.imports,public.events,public.import_events,
  public.resource_requests,public.issues,public.calendar_items,public.export_files to authenticated;
alter table public.profiles enable row level security;
alter table public.invitations enable row level security;
alter table public.imports enable row level security;
alter table public.events enable row level security;
alter table public.import_events enable row level security;
alter table public.resource_requests enable row level security;
alter table public.issues enable row level security;
alter table public.calendar_items enable row level security;
alter table public.export_files enable row level security;
create policy profile_read on public.profiles for select to authenticated using (id=auth.uid() or public.ems_role()='admin');
create policy invitation_read on public.invitations for select to authenticated using (public.ems_role()='admin');
create policy import_read on public.imports for select to authenticated using (public.ems_role()='admin' or (public.ems_role() is not null and status='approved'));
create policy event_read on public.events for select to authenticated using (public.ems_role() is not null);
create policy import_event_read on public.import_events for select to authenticated using (public.ems_role() is not null);
create policy resource_read on public.resource_requests for select to authenticated using (public.ems_role() is not null);
create policy issue_read on public.issues for select to authenticated using (public.ems_role() is not null);
create policy calendar_read on public.calendar_items for select to authenticated using (public.ems_role() is not null);
create policy export_read on public.export_files for select to authenticated using (public.ems_role() is not null and expires_at>now()
  and exists(select from public.imports i where i.id=import_id and (i.status='approved' or public.ems_role()='admin')));

insert into storage.buckets(id,name,public,file_size_limit,allowed_mime_types) values
  ('ems-private','ems-private',false,50000000,array['application/vnd.ms-excel','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','application/octet-stream']);
create policy ems_private_insert on storage.objects for insert to authenticated with check (
  bucket_id='ems-private' and public.ems_role()='admin' and exists(select from public.imports i
    where i.id::text=split_part(name,'/',1) and i.status='processing'));
create policy ems_private_read on storage.objects for select to authenticated using (
  bucket_id='ems-private' and (public.ems_role()='admin' or
    (public.ems_role() is not null and exists(select from public.export_files e join public.imports i on i.id=e.import_id
      where e.storage_path=name and e.expires_at>now() and i.status='approved'))));
-- No UPDATE/DELETE storage policies: source objects cannot be replaced, even via a direct client.

-- Supabase grants EXECUTE to PUBLIC by default: explicitly remove that default for our functions.
revoke all on function public.invited_profile() from public,anon,authenticated;
revoke all on function public.ems_require(text[]) from public,anon;
revoke all on function public.ems_role() from public,anon;
revoke all on function public.ems_normalize(text) from public,anon;
grant execute on function public.ems_require(text[]),public.ems_role(),public.ems_normalize(text) to authenticated;
do $$ declare fn record; begin
  for fn in select p.oid::regprocedure as signature from pg_proc p join pg_namespace n on n.oid=p.pronamespace
    where n.nspname='public' and p.proname=any(array['begin_invitation','revoke_invitation','accept_invitation','set_profile_role',
      'register_import','claim_import','fail_import','finish_import','preview_import','approve_import','update_planning',
      'resolve_issue','save_calendar','query_calendar']) loop
    execute format('revoke all on function %s from public,anon',fn.signature);
    execute format('grant execute on function %s to authenticated',fn.signature);
  end loop;
end $$;
commit;
