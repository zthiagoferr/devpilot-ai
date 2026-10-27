/** Public types shared by the auth service, the dialog and the shell. */

export type AuthMode = 'login' | 'register' | 'reset';

/** Minimal, UI-facing projection of a Firebase user. */
export interface AuthUser {
  readonly uid: string;
  readonly email: string | null;
  readonly displayName: string | null;
  readonly emailVerified: boolean;
}

export type AuthStatus = 'idle' | 'loading' | 'ready' | 'unconfigured' | 'error';

export interface AuthResult {
  readonly ok: boolean;
  readonly message: string;
}

export function userFromFirebase(user: {
  uid: string;
  email: string | null;
  displayName: string | null;
  emailVerified: boolean;
}): AuthUser {
  return {
    uid: user.uid,
    email: user.email,
    displayName: user.displayName,
    emailVerified: user.emailVerified,
  };
}

/** Two-letter avatar label: display name, else e-mail, else "V" (visitor). */
export function initialsFor(user: AuthUser | null): string {
  const source = (user?.displayName || user?.email || '').trim();
  if (source === '') {
    return 'V';
  }
  const words = source.split(/[\s._-]+/).filter((part) => part !== '');
  if (words.length >= 2) {
    return `${words[0]?.[0] ?? ''}${words[1]?.[0] ?? ''}`.toUpperCase();
  }
  return source.slice(0, 2).toUpperCase();
}
