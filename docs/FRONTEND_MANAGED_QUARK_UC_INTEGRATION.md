# Frontend Managed QuarkTV / UCTV Integration

QuarkTV and UCTV are CyberStream-managed OpenList sources. The frontend only calls CyberStream HTTPS APIs. OpenList stays on localhost and is never exposed to clients.

## Discovery

```http
GET /api/v1/storage/provider-types
GET /api/v1/storage/capabilities
GET /api/v1/docs/frontend-managed-quark-uc
```

Expected provider types:

```json
{
  "type": "quarktv",
  "display_name": "QuarkTV",
  "capabilities": {
    "managed": true,
    "qr_login": true,
    "preview": true,
    "scan": true,
    "refresh": true,
    "stream": true,
    "redirect_stream": true
  }
}
```

`uctv` has the same shape with `display_name=UCTV`.

## QuarkTV QR Login

Start:

```http
POST /api/v1/storage/managed/quarktv/qr/start
Content-Type: application/json
```

Request body:

```json
{
  "name": "QuarkTV",
  "root_folder_id": "0",
  "link_method": "download"
}
```

Fields:

- `name` or `source_name`: optional source display name.
- `root_folder_id`: optional OpenList root folder id. Default is `0`.
- `link_method`: optional, `download` or `streaming`. Default is `download`. For first联调 use `download`.

Success response:

```json
{
  "code": 200,
  "data": {
    "qr_started": true,
    "auth_state": "qr_pending",
    "qr_code_data_url": "data:image/jpeg;base64,...",
    "qr_content": null,
    "source": {
      "id": 12,
      "type": "quarktv",
      "config": {
        "auth_state": "qr_pending",
        "cloud_root_path": "/",
        "link_method": "download"
      },
      "actions": {
        "can_preview": false,
        "can_scan": false,
        "can_stream": false,
        "can_refresh": false
      }
    }
  }
}
```

Frontend must display `qr_code_data_url` directly as an image. Do not parse OpenList HTML and do not call OpenList.

Poll:

```http
POST /api/v1/storage/managed/quarktv/qr/poll
Content-Type: application/json
```

Request body:

```json
{
  "source_id": 12
}
```

Pending response:

```json
{
  "code": 200,
  "data": {
    "authenticated": false,
    "auth_state": "qr_pending",
    "pending_reason": "waiting_for_scan",
    "source": {
      "id": 12,
      "type": "quarktv",
      "actions": {
        "can_preview": false,
        "can_scan": false,
        "can_stream": false,
        "can_refresh": false
      }
    }
  }
}
```

Ready response:

```json
{
  "code": 200,
  "data": {
    "authenticated": true,
    "auth_state": "ready",
    "source": {
      "id": 12,
      "type": "quarktv",
      "config": {
        "auth_state": "ready",
        "cloud_root_path": "/",
        "link_method": "download"
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

Poll every 2 to 3 seconds while the login screen is open. Stop polling once `authenticated=true` or the user cancels.

## UCTV QR Login

UCTV uses the same contract with these paths:

```http
POST /api/v1/storage/managed/uctv/qr/start
POST /api/v1/storage/managed/uctv/qr/poll
```

Request and response fields are identical to QuarkTV. The returned source `type` is `uctv`.

## Preview After Login

There is no separate managed preview endpoint. After `auth_state=ready`, use the normal saved-source preview:

```http
GET /api/v1/storage/sources/{source_id}/browse?path=/&dirs_only=true
```

For pure preview before creating a media library, call saved-source browse. For scanning, bind this source to a Library first, or call scan with an explicit `root_path`.

## Streaming

CyberStream resolves the local OpenList `/d` redirect and returns the final provider URL to the frontend. Clients must play the URL returned by CyberStream playback APIs; they never receive or need the localhost OpenList address.

## Deletion

```http
DELETE /api/v1/storage/sources/{source_id}
```

Deleting a managed `quarktv` or `uctv` source also best-effort deletes the corresponding localhost OpenList storage entry. OpenList cleanup failure is logged but does not block source deletion.

## Errors

- `40001`: missing required field, usually `source_id`.
- `40036`: invalid field type or invalid enum, for example `link_method`.
- `40061`: wrong source type, missing internal OpenList storage id, or source not ready.
- `40060`: managed OpenList is disabled or not configured.
- `50260`: localhost OpenList admin call failed.

## Frontend Rules

- Use exactly `/api/v1/storage/managed/quarktv/qr/*` and `/api/v1/storage/managed/uctv/qr/*`.
- Do not try `/v1/...`, `/managed/QuarkTV/...`, or generic `/storage/sources` creation for these managed providers.
- Do not expose or persist OpenList `openlist_storage_id` or `mount_path`; backend strips them from response `source.config`.
- Treat `actions` as the authority for whether preview, scan, stream, or refresh buttons are enabled.
