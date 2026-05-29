# Frontend Managed 123Pan Integration

123Pan is a CyberStream-managed OpenList source. The frontend only calls CyberStream HTTPS APIs. OpenList stays on localhost and is never exposed to clients.

123Pan currently uses account/password login in OpenList. It is not a QR or SMS flow. Do not label this UI as scan login.

## Discovery

```http
GET /api/v1/storage/provider-types
GET /api/v1/storage/capabilities
GET /api/v1/docs/frontend-managed-123pan
```

Expected provider type:

```json
{
  "type": "123pan",
  "display_name": "123Pan",
  "capabilities": {
    "managed": true,
    "password_login": true,
    "preview": true,
    "scan": true,
    "refresh": true,
    "stream": true,
    "redirect_stream": true
  }
}
```

## Login

```http
POST /api/v1/storage/managed/123pan/login
Content-Type: application/json
```

Request body:

```json
{
  "name": "123Pan",
  "username": "13800000000",
  "password": "account-password",
  "root_folder_id": "0",
  "platform": "web"
}
```

Fields:

- `name` or `source_name`: optional source display name. Default is `123Pan`.
- `username`: required. 123Pan account, phone number, or email.
- `password`: required. 123Pan account password.
- `root_folder_id`: optional OpenList root folder id. Default is `0`.
- `platform`: optional OpenList `platform` header. Default is `web`.

Success response:

```json
{
  "code": 200,
  "data": {
    "authenticated": true,
    "auth_state": "ready",
    "source": {
      "id": 12,
      "type": "123pan",
      "display_name": "123Pan",
      "config": {
        "auth_state": "ready",
        "cloud_root_path": "/",
        "root_folder_id": "0",
        "account_name_masked": "13*****0000",
        "platform": "web"
      },
      "actions": {
        "can_preview": true,
        "can_scan": true,
        "can_stream": true,
        "can_refresh": true
      }
    }
  }
}
```

The response never exposes OpenList `openlist_storage_id`, `mount_path`, the account password, or the localhost OpenList address.

## Preview After Login

Use the normal saved-source browse endpoint:

```http
GET /api/v1/storage/sources/{source_id}/browse?path=/&dirs_only=true
```

For scanning, bind this source to a Library first, or call scan with an explicit `root_path`.

## Streaming

CyberStream resolves the local OpenList `/d` redirect and returns the provider URL to the frontend. Clients must play the URL returned by CyberStream playback APIs; they never receive or need the localhost OpenList address.

If 123Pan changes playback requirements later, treat CyberStream playback response fields as authoritative rather than deriving behavior from OpenList.

## Deletion

```http
DELETE /api/v1/storage/sources/{source_id}
```

Deleting a managed `123pan` source also best-effort deletes the corresponding localhost OpenList storage entry. OpenList cleanup failure is logged but does not block source deletion.

## Errors

- `40001`: missing required field, usually `username` or `password`.
- `40038`: invalid source name.
- `40060`: managed OpenList is disabled or not configured.
- `40061`: created storage is not a 123Pan managed source, or the source is not ready.
- `50260`: localhost OpenList admin call or 123Pan login failed.

## Frontend Rules

- Use exactly `/api/v1/storage/managed/123pan/login`.
- Do not try `/v1/...`, `/managed/123Pan/...`, or generic `/storage/sources` creation for this managed provider.
- Do not persist or display the password after submit.
- Do not expose or persist OpenList `openlist_storage_id` or `mount_path`; backend strips them from response `source.config`.
- Treat `actions` as the authority for whether preview, scan, stream, or refresh buttons are enabled.
