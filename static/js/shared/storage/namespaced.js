const SEGMENT = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

export function namespacedKey(domain, subject, version = 1) {
  if (!SEGMENT.test(domain) || !SEGMENT.test(subject)) {
    throw new TypeError('Storage namespace segments must be lowercase kebab-case');
  }
  if (!Number.isInteger(version) || version < 1) {
    throw new TypeError('Storage schema version must be a positive integer');
  }
  return `studio:${domain}:${subject}:v${version}`;
}
