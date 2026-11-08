-- The settings of OIDC sign-in (#166, step 1 of docs/design/oidc). A Boolean is a kind of setting: the text `true` or `false`, shown
-- as a Yes or No choice and read as a real boolean. OIDC is off, the creation of users by the provider is off, and local sign-in
-- is on until an admin changes them. The client secret and the public address are deployment settings (environment
-- variables), never properties. The validators refuse a configuration that could lock everyone out. See docs/decisions.md.

INSERT INTO ref_property_data_types (name) VALUES ('Boolean');

INSERT INTO system_properties (name, data_type_id, value, allow_null, hint, created_by, updated_by)
SELECT name, (SELECT id FROM ref_property_data_types WHERE name = type), value, allow_null, hint,
       (SELECT id FROM users WHERE is_system = 1), (SELECT id FROM users WHERE is_system = 1)
FROM (
    SELECT 'oidc.enabled' AS name, 'Boolean' AS type, 'false' AS value, 0 AS allow_null,
           'Whether people can sign in through the OIDC provider set below. It needs the issuer, client ID, client secret and public address, and can''t be turned off while password sign-in is off.' AS hint
    UNION ALL SELECT 'oidc.provider', 'String', NULL, 1,
           'The name on the sign-in button, such as Pocket ID or Authentik. It changes nothing else.'
    UNION ALL SELECT 'oidc.issuer', 'String', NULL, 1,
           'The provider''s exact issuer address, such as https://id.example.com, from which Northstar finds its endpoints and keys. Changing it ends every OIDC session.'
    UNION ALL SELECT 'oidc.client_id', 'String', NULL, 1,
           'The client ID the provider gave Northstar. The client secret is not a setting: give it to the app through the environment.'
    UNION ALL SELECT 'oidc.user.allow_creation', 'Boolean', 'false', 0,
           'Yes creates an account for anyone the provider signs in with a verified email, and it can see all household financial data. Existing users are linked by email whatever this says.'
    UNION ALL SELECT 'oidc.session.lifetime_hours', 'Integer', '12', 0,
           'How long a new OIDC session lasts, in hours from sign-in (1 to 8760). Using Northstar doesn''t extend it. Sessions already started keep theirs.'
    UNION ALL SELECT 'system.auth.local.enabled', 'Boolean', 'true', 0,
           'Whether people can sign in with an email and password. It can be turned off only once OIDC works and an admin has signed in through it. Locked out? Run python -m northstar.signin enable-local on the host.'
);

INSERT INTO ref_property_validators (property_id, validator, position)
SELECT id, validator, 1 FROM system_properties JOIN (
    SELECT 'oidc.enabled' AS n, 'oidc_enabled' AS validator
    UNION ALL SELECT 'oidc.issuer', 'oidc_issuer'
    UNION ALL SELECT 'oidc.client_id', 'oidc_client_id'
    UNION ALL SELECT 'oidc.session.lifetime_hours', 'oidc_session_hours'
    UNION ALL SELECT 'system.auth.local.enabled', 'local_signin'
) ON n = name;
