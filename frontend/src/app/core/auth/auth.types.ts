/** Public types shared by the auth service, the dialog and the shell. */

export type AuthMode = 'login' | 'register' | 'reset';

/** Minimal, UI-facing projection of a Firebase user. */
export interface AuthUser {
  readonly uid: string;
  readonly email: string | null;
  readonly displayName: string | null;
  readonly emailVerified: boolean;
  /** True for anonymous (guest) sessions. */
  readonly isAnonymous: boolean;
}

export type AuthStatus = 'idle' | 'loading' | 'ready' | 'unconfigured' | 'error';

export interface AuthResult {
  readonly ok: boolean;
  readonly message: string;
  /** Optional presentation hint; success when omitted. */
  readonly tone?: 'success' | 'warning';
}

/** Projects a Firebase user into the UI-facing shape. */
export function userFromFirebase(user: {
  uid: string;
  email: string | null;
  displayName: string | null;
  emailVerified: boolean;
  isAnonymous?: boolean;
}): AuthUser {
  return {
    uid: user.uid,
    email: user.email,
    displayName: user.displayName,
    emailVerified: user.emailVerified,
    isAnonymous: user.isAnonymous ?? false,
  };
}

/** True only for a non-anonymous account with an unconfirmed e-mail. */
export function needsEmailVerification(user: AuthUser | null): boolean {
  return user !== null && !user.isAnonymous && (user.email ?? '') !== '' && !user.emailVerified;
}

/** Field-by-field comparison used to avoid redundant signal writes. */
export function sameAuthUser(a: AuthUser | null, b: AuthUser | null): boolean {
  if (a === b) {
    return true;
  }
  if (a === null || b === null) {
    return false;
  }
  return (
    a.uid === b.uid &&
    a.email === b.email &&
    a.displayName === b.displayName &&
    a.emailVerified === b.emailVerified &&
    a.isAnonymous === b.isAnonymous
  );
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
