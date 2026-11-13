alter table history
    drop constraint if exists history_event_type_check;

alter table history
    add constraint history_event_type_check
    check (event_type in (
        'created',
        'scored',
        'stage_changed',
        'updated',
        'alert_sent',
        'alert_failed',
        'alert_parked',
        'alert_skipped',
        'alert_resent'
    ));