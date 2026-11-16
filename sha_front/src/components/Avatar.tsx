import { useState, type ReactElement } from 'react';
import { avatarUrl } from '../config';

/**
 * A submitter's GitHub profile picture. Decorative: the name beside it says who it is. If
 * GitHub cannot serve it (an account deleted, the network down), nothing is shown rather
 * than a broken image.
 */
export function Avatar({ githubUserId, size }: { githubUserId: number; size: number }): ReactElement | null {
  const [failed, setFailed] = useState(false);
  if (failed) {
    return null;
  }
  return (
    <img className="avatar" src={avatarUrl(githubUserId, size)} width={size} height={size} alt=""
      loading="lazy" decoding="async" referrerPolicy="no-referrer" onError={() => setFailed(true)} />
  );
}
