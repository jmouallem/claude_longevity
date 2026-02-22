type BinaryLike = ArrayBuffer | Uint8Array;

function toArrayBuffer(value: BinaryLike): ArrayBuffer {
  if (value instanceof ArrayBuffer) {
    return value;
  }
  return value.buffer.slice(value.byteOffset, value.byteOffset + value.byteLength) as ArrayBuffer;
}

function base64urlToArrayBuffer(base64url: string): ArrayBuffer {
  const padded = base64url.replace(/-/g, '+').replace(/_/g, '/');
  const padLength = (4 - (padded.length % 4)) % 4;
  const normalized = `${padded}${'='.repeat(padLength)}`;
  const decoded = window.atob(normalized);
  const bytes = new Uint8Array(decoded.length);
  for (let i = 0; i < decoded.length; i += 1) {
    bytes[i] = decoded.charCodeAt(i);
  }
  return bytes.buffer;
}

function arrayBufferToBase64url(input: BinaryLike | null | undefined): string {
  if (!input) return '';
  const bytes = new Uint8Array(toArrayBuffer(input));
  let binary = '';
  for (let i = 0; i < bytes.byteLength; i += 1) {
    binary += String.fromCharCode(bytes[i]);
  }
  return window
    .btoa(binary)
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/g, '');
}

function toPublicKeyCreationOptions(raw: Record<string, unknown>): PublicKeyCredentialCreationOptions {
  const copy: Record<string, unknown> = { ...raw };
  copy.challenge = base64urlToArrayBuffer(String(raw.challenge || ''));

  const user = (raw.user as Record<string, unknown> | undefined) || {};
  copy.user = {
    ...user,
    id: base64urlToArrayBuffer(String(user.id || '')),
  };

  const excludeCredentials = Array.isArray(raw.excludeCredentials) ? raw.excludeCredentials : [];
  copy.excludeCredentials = excludeCredentials.map((item) => {
    const descriptor = (item as Record<string, unknown>) || {};
    return {
      ...descriptor,
      id: base64urlToArrayBuffer(String(descriptor.id || '')),
    };
  });

  return copy as unknown as PublicKeyCredentialCreationOptions;
}

function toPublicKeyRequestOptions(raw: Record<string, unknown>): PublicKeyCredentialRequestOptions {
  const copy: Record<string, unknown> = { ...raw };
  copy.challenge = base64urlToArrayBuffer(String(raw.challenge || ''));

  const allowCredentials = Array.isArray(raw.allowCredentials) ? raw.allowCredentials : [];
  copy.allowCredentials = allowCredentials.map((item) => {
    const descriptor = (item as Record<string, unknown>) || {};
    return {
      ...descriptor,
      id: base64urlToArrayBuffer(String(descriptor.id || '')),
    };
  });
  return copy as unknown as PublicKeyCredentialRequestOptions;
}

function credentialToJSON(credential: PublicKeyCredential): Record<string, unknown> {
  const response = credential.response;
  const base: Record<string, unknown> = {
    id: credential.id,
    rawId: arrayBufferToBase64url(credential.rawId),
    type: credential.type,
    clientExtensionResults: credential.getClientExtensionResults(),
  };

  if ('attestationObject' in response) {
    const attestationResponse = response as AuthenticatorAttestationResponse;
    base.response = {
      clientDataJSON: arrayBufferToBase64url(attestationResponse.clientDataJSON),
      attestationObject: arrayBufferToBase64url(attestationResponse.attestationObject),
      transports: typeof attestationResponse.getTransports === 'function'
        ? attestationResponse.getTransports()
        : undefined,
      publicKeyAlgorithm: (attestationResponse as unknown as { getPublicKeyAlgorithm?: () => number }).getPublicKeyAlgorithm?.(),
      publicKey: arrayBufferToBase64url((attestationResponse as unknown as { getPublicKey?: () => ArrayBuffer | null }).getPublicKey?.() || undefined),
      authenticatorData: arrayBufferToBase64url((attestationResponse as unknown as { getAuthenticatorData?: () => ArrayBuffer | null }).getAuthenticatorData?.() || undefined),
    };
    return base;
  }

  const assertionResponse = response as AuthenticatorAssertionResponse;
  base.response = {
    clientDataJSON: arrayBufferToBase64url(assertionResponse.clientDataJSON),
    authenticatorData: arrayBufferToBase64url(assertionResponse.authenticatorData),
    signature: arrayBufferToBase64url(assertionResponse.signature),
    userHandle: arrayBufferToBase64url(assertionResponse.userHandle || undefined),
  };
  return base;
}

export function isWebAuthnSupported(): boolean {
  return typeof window !== 'undefined' && !!window.PublicKeyCredential;
}

export async function createPasskeyCredential(options: Record<string, unknown>): Promise<Record<string, unknown>> {
  if (!isWebAuthnSupported()) {
    throw new Error('This device/browser does not support biometrics passkeys.');
  }
  const credential = await navigator.credentials.create({
    publicKey: toPublicKeyCreationOptions(options),
  });
  if (!credential) {
    throw new Error('Passkey creation was cancelled.');
  }
  return credentialToJSON(credential as PublicKeyCredential);
}

export async function getPasskeyAssertion(options: Record<string, unknown>): Promise<Record<string, unknown>> {
  if (!isWebAuthnSupported()) {
    throw new Error('This device/browser does not support biometrics passkeys.');
  }
  const credential = await navigator.credentials.get({
    publicKey: toPublicKeyRequestOptions(options),
  });
  if (!credential) {
    throw new Error('Biometric sign-in was cancelled.');
  }
  return credentialToJSON(credential as PublicKeyCredential);
}
