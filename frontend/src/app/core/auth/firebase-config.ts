/**
 * Public Firebase web configuration and its runtime override.
 *
 * These values identify the Firebase project in the browser and are public by
 * design — they are not secrets. The backend uses a service account (never
 * shipped here) to verify the ID tokens issued for this project. `measurementId`
 * is intentionally omitted: it only feeds Google Analytics, and this bundle
 * imports no analytics SDK.
 *
 * `window.DevPilotConfig.firebase` may override any value at deploy time. The
 * override is merged with the defaults below, so disabling authentication in a
 * deployment requires explicitly setting `apiKey` and `projectId` to empty
 * strings; an absent override keeps the versioned project. Independently of
 * that static check, the app degrades at runtime when the SDK bootstrap fails,
 * so a deployment where Firebase is unreachable never opens a dead login form.
 */
export interface FirebaseRuntimeConfig {
  readonly apiKey?: string;
  readonly authDomain?: string;
  readonly projectId?: string;
  readonly storageBucket?: string;
  readonly messagingSenderId?: string;
  readonly appId?: string;
  /**
   * Optional allow-list of OAuth provider ids (`github`, `google`, `apple`,
   * `microsoft`). Absent (or empty) means every provider is available.
   *
   * This key is app configuration only and is stripped before the object is
   * handed to `initializeApp`.
   */
  readonly providers?: readonly string[];
}

export const FIREBASE_CONFIG: FirebaseRuntimeConfig = {
  apiKey: 'AIzaSyDGFEavZI0KnlUjhqk6DAJ8eRWId4n-7Fg',
  authDomain: 'devpilot-ai-e78f0.firebaseapp.com',
  projectId: 'devpilot-ai-e78f0',
  storageBucket: 'devpilot-ai-e78f0.firebasestorage.app',
  messagingSenderId: '760068755230',
  appId: '1:760068755230:web:f7b542b79b3b6277fdc30f',
};

export function resolveFirebaseConfig(
  override?: FirebaseRuntimeConfig | null,
): FirebaseRuntimeConfig {
  if (override === undefined || override === null) {
    return FIREBASE_CONFIG;
  }

  const defined = Object.fromEntries(
    Object.entries(override).filter(([, value]) => value !== undefined && value !== null),
  ) as FirebaseRuntimeConfig;

  return { ...FIREBASE_CONFIG, ...defined };
}

export function isFirebaseConfigured(config: FirebaseRuntimeConfig | undefined): boolean {
  return (config?.apiKey ?? '') !== '' && (config?.projectId ?? '') !== '';
}
