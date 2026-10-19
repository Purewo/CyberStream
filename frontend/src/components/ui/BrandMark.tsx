import React from 'react';

interface BrandMarkProps {
  text?: string;
  variant?: 'nav' | 'login' | 'footer';
  className?: string;
  onClick?: () => void;
  ariaLabel?: string;
}

export const BrandMark: React.FC<BrandMarkProps> = ({
  text = 'CYBER//STREAM',
  variant = 'nav',
  className = '',
  onClick,
  ariaLabel,
}) => {
  const classes = ['brand-mark', `brand-mark--${variant}`, onClick ? 'brand-mark--button' : '', className]
    .filter(Boolean)
    .join(' ');

  const mark = (
    <>
      <span className="brand-mark__base">{text}</span>
      <span className="brand-mark__sweep" aria-hidden="true">{text}</span>
    </>
  );

  if (onClick) {
    return (
      <button type="button" className={classes} onClick={onClick} aria-label={ariaLabel || text}>
        {mark}
      </button>
    );
  }

  return (
    <span className={classes} aria-label={ariaLabel || text}>
      {mark}
    </span>
  );
};
