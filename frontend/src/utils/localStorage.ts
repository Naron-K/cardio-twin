// Profile persistence in localStorage

export interface Profile {
  id: string
  name: string
  timestamp: string
  values: Record<string, number>
}

const PROFILES_KEY = 'cardiotwin_profiles'

export function getProfiles(): Profile[] {
  try {
    const raw = localStorage.getItem(PROFILES_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw) as Profile[]
    return parsed.sort(
      (a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()
    )
  } catch {
    return []
  }
}

export function saveProfile(name: string, values: Record<string, number>): Profile {
  const profiles = getProfiles()
  const profile: Profile = {
    id: crypto.randomUUID(),
    name,
    timestamp: new Date().toISOString(),
    values,
  }
  profiles.push(profile)
  localStorage.setItem(PROFILES_KEY, JSON.stringify(profiles))
  return profile
}

export function deleteProfile(id: string): void {
  const remaining = getProfiles().filter((p) => p.id !== id)
  localStorage.setItem(PROFILES_KEY, JSON.stringify(remaining))
}

// Build a minimal patient XML from sensor values (client-side, no backend needed)
export function buildPatientXML(name: string, values: Record<string, number>): string {
  const created = new Date().toISOString()
  const sensors = Object.entries(values)
    .map(([k, v]) => `    <${k}>${v}</${k}>`)
    .join('\n')
  return [
    '<?xml version="1.0" encoding="utf-8"?>',
    '<patient>',
    `  <name>${name}</name>`,
    `  <created>${created}</created>`,
    '  <sensor_data>',
    sensors,
    '  </sensor_data>',
    '</patient>',
  ].join('\n')
}
