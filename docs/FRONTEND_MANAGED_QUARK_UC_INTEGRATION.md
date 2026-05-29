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
- `link_method`: optional, `download` or `streaming`. Default is `download`. The frontend should expose this as a user choice when mounting QuarkTV:
  - `download`: OpenList download link mode.
  - `streaming`: OpenList streaming link mode. For Web/Android playback, prefer this as the UI default.

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
        "root_folder_id": "0",
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
        "root_folder_id": "0",
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

## QuarkTV Re-login Existing Source

QuarkTV TV login can be kicked offline when the same account is used elsewhere. Do not create a new CyberStream source for re-login, because that breaks existing resource indexes and library bindings. Restart QR login on the existing source:

```http
POST /api/v1/storage/managed/quarktv/qr/restart
Content-Type: application/json
```

Request body:

```json
{
  "source_id": 12,
  "link_method": "streaming"
}
```

Fields:

- `source_id` or `id`: required existing CyberStream QuarkTV source id.
- `link_method`: optional, `download` or `streaming`. If omitted, backend keeps the source's previous `config.link_method`.
- `root_folder_id`: optional. If omitted, backend keeps the source's previous `config.root_folder_id`.

Success response:

```json
{
  "code": 200,
  "data": {
    "qr_restarted": true,
    "qr_started": true,
    "auth_state": "qr_pending",
    "replaced_openlist_storage_id": 41,
    "old_openlist_storage_deleted": true,
    "qr_code_data_url": "data:image/jpeg;base64,...",
    "qr_content": null,
    "source": {
      "id": 12,
      "type": "quarktv",
      "config": {
        "auth_state": "qr_pending",
        "cloud_root_path": "/",
        "root_folder_id": "0",
        "link_method": "streaming"
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

After restart, poll the normal QuarkTV poll endpoint with the same `source_id` until `authenticated=true`.

## UCTV QR Login

UCTV uses the same contract with these paths:

```http
POST /api/v1/storage/managed/uctv/qr/start
POST /api/v1/storage/managed/uctv/qr/restart
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

QuarkTV/UCTV raw download links are not reliable for web playback. For video playback UI, prefer the cloud transcoding contract exposed in `playback.cloud_transcode`.

Resource playback payload:

```json
{
  "playback": {
    "storage_type": "quarktv",
    "stream_url": "/api/v1/resources/{resource_id}/stream",
    "cloud_transcode": {
      "supported": true,
      "provider": "quarktv",
      "provider_name": "QuarkTV",
      "mode": "provider_cloud_transcode",
      "qualities_endpoint": "/api/v1/resources/{resource_id}/streaming-qualities",
      "stream_endpoint": "/api/v1/resources/{resource_id}/stream-transcoded",
      "resolution_param": "resolution",
      "available_resolutions": ["low", "normal", "high", "super", "2k", "4k"]
    },
    "warnings": [
      {
        "code": "quark_uc_download_link_not_web_playable",
        "message": "QuarkTV/UCTV raw download links may not play in web players; use playback.cloud_transcode."
      }
    ]
  }
}
```

Fetch available provider transcoding qualities:

```http
GET /api/v1/resources/{resource_id}/streaming-qualities
```

Response fields:

- `default_resolution`: provider default quality, for example `4k`.
- `selected_resolution` / `selected_item`: backend-selected playable quality. If the request includes `?resolution=super`, the selected item will be that quality or the API returns `409`.
- `items[].resolution`: one of `low`, `normal`, `high`, `super`, `2k`, `4k`.
- `items[].available`: only `true` items should be shown as playable choices.
- `items[].width` / `height` / `size` / `bitrate` / `format`: display metadata returned by the provider.
- `items[].stream_url`: CyberStream 302 endpoint for this exact quality.
- `items[].url`: provider transcoded direct URL. It is not a localhost OpenList URL and may expire. Frontend can prefer `stream_url`.

Example:

```json
{
  "code": 200,
  "data": {
    "resource_id": "11111111-1111-1111-1111-111111111111",
    "storage_type": "quarktv",
    "provider": "QuarkTV",
    "mode": "provider_cloud_transcode",
    "default_resolution": "4k",
    "selected_resolution": "4k",
    "items": [
      {
        "resolution": "low",
        "label": "LD",
        "available": true,
        "width": 480,
        "height": 270,
        "size": 157900849,
        "trans_status": "success",
        "stream_url": "/api/v1/resources/{resource_id}/stream-transcoded?resolution=low"
      },
      {
        "resolution": "super",
        "label": "FHD",
        "available": true,
        "width": 1440,
        "height": 810,
        "size": 688010711,
        "trans_status": "success",
        "stream_url": "/api/v1/resources/{resource_id}/stream-transcoded?resolution=super"
      },
      {
        "resolution": "4k",
        "label": "4K",
        "available": true,
        "width": 3840,
        "height": 2160,
        "size": 3368152792,
        "trans_status": "success",
        "stream_url": "/api/v1/resources/{resource_id}/stream-transcoded?resolution=4k"
      }
    ]
  }
}
```

Play a selected quality:

```http
GET /api/v1/resources/{resource_id}/stream-transcoded?resolution=super
```

The response is a `302` redirect to the provider transcoded URL. `quality` is accepted as a compatibility alias, but new frontend code should use `resolution`.

## Deletion

```http
DELETE /api/v1/storage/sources/{source_id}
```

Deleting a managed `quarktv` or `uctv` source also best-effort deletes the corresponding localhost OpenList storage entry. OpenList cleanup failure is logged but does not block source deletion.

## Errors

- `40001`: missing required field, usually `source_id`.
- `40036`: invalid field type or invalid enum, for example `link_method`.
- `40061`: wrong source type, missing internal OpenList storage id, or source not ready.
- `40074`: resource source does not support cloud transcoding.
- `40075`: unsupported transcoding resolution or empty resource path.
- `40404`: provider file path cannot be resolved to a QuarkTV/UCTV file id.
- `40913`: requested transcoding resolution is not available.
- `40060`: managed OpenList is disabled or not configured.
- `50260`: localhost OpenList admin call failed.
- `50290`-`50294`: provider TV API or token refresh failed.

## Frontend Rules

- Use exactly `/api/v1/storage/managed/quarktv/qr/*` and `/api/v1/storage/managed/uctv/qr/*`.
- Do not try `/v1/...`, `/managed/QuarkTV/...`, or generic `/storage/sources` creation for these managed providers.
- Do not expose or persist OpenList `openlist_storage_id` or `mount_path`; backend strips them from response `source.config`.
- Treat `actions` as the authority for whether preview, scan, stream, or refresh buttons are enabled.
- For QuarkTV/UCTV playback, prefer `playback.cloud_transcode.qualities_endpoint` and play `items[].stream_url`; raw `playback.stream_url` is still present for compatibility but may not play in web players.
