// Frozen cross-page message contract. Keep values aligned with compat-contract §§1-3.
export const StudioMessageType = Object.freeze({
  CANVAS_FOCUS: 'canvas-focus',
  STUDIO_THEME: 'studio-theme',
  STUDIO_UI_SCALE: 'studio-ui-scale',
  STUDIO_UI_SCALE_PAUSE: 'studio-ui-scale-pause',
  STUDIO_LANG: 'studio-lang',
  PROVIDERS_CHANGED: 'providers-changed',
  WORKFLOWS_CHANGED: 'workflows-changed',
  COMFY_INSTANCES_CHANGED: 'comfy-instances-changed',
  STATS: 'stats',
  CLOUD_STATUS: 'cloud_status',
  CANVAS_UPDATED: 'canvas_updated',
  ASSET_LIBRARY_UPDATED: 'asset_library_updated',
  NEW_IMAGE: 'new_image',
  PONG: 'pong',
});

export const STUDIO_MESSAGE_TYPES = Object.freeze(Object.values(StudioMessageType));
const STUDIO_MESSAGE_TYPE_SET = new Set(STUDIO_MESSAGE_TYPES);

const optional = (value, predicate) => value === undefined || predicate(value);
const string = value => typeof value === 'string';
const finiteNumber = value => typeof value === 'number' && Number.isFinite(value);

const PAYLOAD_VALIDATORS = Object.freeze({
  [StudioMessageType.CANVAS_FOCUS]: value => optional(value.canvas_id, string),
  [StudioMessageType.STUDIO_THEME]: value => optional(value.theme, string),
  [StudioMessageType.STUDIO_UI_SCALE]: value => (
    optional(value.mode, string) && optional(value.scale, finiteNumber)
  ),
  [StudioMessageType.STUDIO_UI_SCALE_PAUSE]: value => optional(value.duration, finiteNumber),
  [StudioMessageType.STUDIO_LANG]: value => optional(value.lang, string),
  [StudioMessageType.PROVIDERS_CHANGED]: value => optional(value.updated_at, finiteNumber),
  [StudioMessageType.WORKFLOWS_CHANGED]: value => optional(value.updated_at, finiteNumber),
  [StudioMessageType.COMFY_INSTANCES_CHANGED]: value => optional(value.updated_at, finiteNumber),
  [StudioMessageType.STATS]: value => optional(value.online_count, finiteNumber),
  [StudioMessageType.CLOUD_STATUS]: value => optional(value.status, string),
  [StudioMessageType.CANVAS_UPDATED]: value => (
    optional(value.canvas_id, string) && optional(value.updated_at, finiteNumber)
  ),
  [StudioMessageType.ASSET_LIBRARY_UPDATED]: value => optional(value.updated_at, finiteNumber),
  [StudioMessageType.NEW_IMAGE]: value => optional(value.url, string),
  [StudioMessageType.PONG]: () => true,
});

export function isStudioMessage(value) {
  if (!value || typeof value !== 'object' || !STUDIO_MESSAGE_TYPE_SET.has(value.type)) return false;
  if (!optional(value.message_id, string) || !optional(value.client_id, string)) return false;
  return PAYLOAD_VALIDATORS[value.type](value);
}

export function assertStudioMessage(value) {
  if (!isStudioMessage(value)) {
    throw new TypeError(`Unknown Studio message type: ${String(value?.type || '')}`);
  }
  return value;
}
