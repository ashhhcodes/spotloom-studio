# API Contracts — AdForge AI

- Status: Proposed contract; implementation may adjust only with documented decisions.
- Prefix: `/api`
- Content type: JSON unless a route explicitly accepts multipart or returns media.
- IDs: opaque random identifiers; never expose filesystem paths.

## 1. Common conventions

### Error shape

```json
{
  "error": {
    "code": "INVALID_URL",
    "message": "Enter a valid public HTTP or HTTPS website URL.",
    "request_id": "req_example"
  }
}
```

Messages must not contain stack traces, secrets, internal IP details, or local paths.

### Job states
- `queued`
- `running`
- `completed`
- `completed_with_warnings`
- `failed`
- `cancelled`

### Scan states
- `ok`
- `partial`
- `blocked`
- `unreachable`
- `invalid_url`
- `timeout`
- `internal_error`

## 2. Health endpoints

### `GET /health`
Liveness only. Returns process alive.

### `GET /ready`
Checks required dependencies are usable. Do not return credentials, full configuration, internal addresses, or sensitive exception text.

## 3. Start website scan

### `POST /api/scans`

Request:
```json
{
  "url": "https://example.com",
  "refresh": false
}
```

Response: `202 Accepted`
```json
{
  "job_id": "job_opaque",
  "status": "queued",
  "stage": "scanning",
  "poll_url": "/api/jobs/job_opaque"
}
```

Validation:
- URL scheme must be HTTP or HTTPS.
- Reject credentials embedded in URLs.
- Resolve and validate destination before every request and redirect.
- Enforce timeout, response-size and crawl limits.

## 4. Get job

### `GET /api/jobs/{job_id}`

Example scan result:
```json
{
  "job_id": "job_opaque",
  "kind": "scan",
  "status": "completed",
  "stage": "scanning",
  "progress_percent": 100,
  "result": {
    "scan_status": "partial",
    "business_facts": [
      {
        "field": "business_name",
        "value": "Example Bakery",
        "source_kind": "website",
        "source_url": "https://example.com/about",
        "review_state": "needs_review"
      }
    ],
    "assets": [
      {
        "asset_id": "asset_opaque",
        "kind": "image",
        "source_url": "https://example.com/image.jpg",
        "width": 1200,
        "height": 800
      }
    ],
    "warnings": ["No public phone number was found."]
  },
  "error": null
}
```

Do not use the example values as real business facts. The API should omit unavailable optional fields rather than inventing them.

## 5. Manual business facts

### `POST /api/businesses/manual`

Request:
```json
{
  "business_name": "Example Bakery",
  "description": "A neighborhood bakery",
  "services": ["Bread", "Pastries"],
  "offer": null,
  "phone": null,
  "address": null,
  "cta_text": "Visit us",
  "cta_url": "https://example.com"
}
```

Validate URL and contact fields. Optional fields should remain null when not provided.

## 6. Create creative

### `POST /api/creatives`

Request:
```json
{
  "business_facts": {
    "business_name": "Example Bakery",
    "description": "A neighborhood bakery",
    "services": ["Bread", "Pastries"],
    "offer": null,
    "phone": null,
    "address": null,
    "approved": true
  },
  "options": {
    "goal": "awareness",
    "tone": "warm",
    "duration_seconds": 10,
    "aspect_ratio": "9:16",
    "style": "clean_product_showcase",
    "cta_text": "Visit us"
  }
}
```

Response:
```json
{
  "creative_id": "creative_opaque",
  "status": "completed",
  "provider_used": "deterministic",
  "creative": {
    "hook": "Freshly baked, close to home.",
    "scenes": [
      {
        "duration_seconds": 3,
        "visual_direction": "Show the approved bakery image with a gentle push-in.",
        "on_screen_text": "Freshly baked",
        "asset_id": "asset_opaque"
      }
    ],
    "cta": {
      "text": "Visit us",
      "destination_url": "https://example.com"
    }
  },
  "validation": {
    "schema_valid": true,
    "unsupported_claims": [],
    "warnings": []
  }
}
```

This is illustrative schema only. Actual creative text must be generated from the approved facts and must not be hard-coded to imply real verification.

## 7. Start ad render

### `POST /api/ads`

Request:
```json
{
  "creative_id": "creative_opaque",
  "asset_ids": ["asset_opaque"],
  "options": {
    "duration_seconds": 10,
    "aspect_ratio": "9:16",
    "include_logo": false,
    "include_qr": false,
    "qr_url": null,
    "keep_audio": false
  }
}
```

Response: `202 Accepted`
```json
{
  "ad_id": "ad_opaque",
  "job_id": "job_opaque",
  "status": "queued",
  "poll_url": "/api/jobs/job_opaque"
}
```

## 8. Get ad result

### `GET /api/ads/{ad_id}`

Response:
```json
{
  "ad_id": "ad_opaque",
  "status": "completed_with_warnings",
  "video_url": "/api/ads/ad_opaque/video",
  "composition": {
    "width": 1080,
    "height": 1920,
    "duration_seconds": 10,
    "codec": "h264"
  },
  "ai_video_used": false,
  "provider_used": "ffmpeg",
  "warnings": ["AI video provider was not configured; an image-motion video was rendered."]
}
```

## 9. Stream or download video

### `GET /api/ads/{ad_id}/video`
- Returns `video/mp4`.
- Supports range requests if practical.
- Uses opaque IDs and authorization checks.
- Does not accept a filesystem path from the client.
- `Content-Disposition` uses a safe generated filename.
- Download access must follow retention and authorization rules.

## 10. Uploads (P1)

### `POST /api/uploads`
Multipart upload for logo/image. Enforce request-size limits, inspect actual file content, decode safely, generate storage names, and reject unsupported formats. Do not trust file extensions or browser-provided MIME types.

## 11. API compatibility policy

- Keep frontend types synchronized with backend schemas.
- Add tests for each public route and key status transition.
- Document breaking changes in `DECISIONS.md`.
- Use stable machine-readable error codes; user-facing wording may improve without breaking clients.
