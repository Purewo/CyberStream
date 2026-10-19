import React, { useEffect, useMemo, useRef, useState } from 'react';

interface ResilientImageProps extends Omit<React.ImgHTMLAttributes<HTMLImageElement>, 'src'> {
  sources: Array<string | null | undefined>;
  fallback?: React.ReactNode;
  maxRetries?: number;
}

export const uniqueImageSources = (sources: Array<string | null | undefined>): string[] => {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const source of sources) {
    const value = typeof source === 'string' ? source.trim() : '';
    if (!value || seen.has(value)) continue;
    seen.add(value);
    result.push(value);
  }
  return result;
};

export const ResilientImage: React.FC<ResilientImageProps> = ({
  sources,
  ...props
}) => {
  const candidates = useMemo(() => uniqueImageSources(sources), [sources]);
  return <ImageCandidates key={JSON.stringify(candidates)} candidates={candidates} {...props} />;
};

const ImageCandidates: React.FC<Omit<ResilientImageProps, 'sources'> & { candidates: string[] }> = ({
  candidates,
  fallback = null,
  maxRetries = 2,
  onError,
  onLoad,
  ...imgProps
}) => {
  const [candidateIndex, setCandidateIndex] = useState(0);
  const [attempt, setAttempt] = useState(0);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => {
    if (timer.current !== null) clearTimeout(timer.current);
  }, []);

  if (candidateIndex >= candidates.length) {
    return <>{fallback}</>;
  }

  return (
    <img
      {...imgProps}
      key={`${candidateIndex}:${attempt}`}
      src={candidates[candidateIndex]}
      onLoad={(event) => {
        if (timer.current !== null) clearTimeout(timer.current);
        timer.current = null;
        onLoad?.(event);
      }}
      onError={(event) => {
        onError?.(event);
        if (timer.current !== null) return;
        if (attempt < maxRetries) {
          // Remount without changing signed image URLs, then try the next source.
          timer.current = setTimeout(() => {
            timer.current = null;
            setAttempt(value => value + 1);
          }, 400 * (attempt + 1));
        } else {
          setAttempt(0);
          setCandidateIndex(index => index + 1);
        }
      }}
    />
  );
};
