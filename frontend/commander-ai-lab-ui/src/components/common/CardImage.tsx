import { useState } from 'react'

interface CardImageProps {
  src: string
  alt: string
  size?: 'sm' | 'md' | 'lg' | 'xl'
  className?: string
  onClick?: () => void
}

const SIZES = {
  sm: 'w-16 h-[22px]',    // tiny inline
  md: 'w-[146px] h-[204px]',  // grid thumbnail
  lg: 'w-[244px] h-[340px]',  // detail view
  xl: 'w-[336px] h-[468px]',  // full size
}

export function CardImage({ src, alt, size = 'md', className = '', onClick }: CardImageProps) {
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState(false)

  // Build Scryfall URL if needed — ensure we get the right size
  const imgUrl = src || ''

  return (
    <div
      className={`relative overflow-hidden rounded-lg bg-bg-tertiary ${SIZES[size]} ${onClick ? 'cursor-pointer hover:ring-2 hover:ring-accent-blue/50 transition-all' : ''} ${className}`}
      onClick={onClick}
    >
      {!error ? (
        <img
          src={imgUrl}
          alt={alt}
          className={`w-full h-full object-cover transition-opacity duration-200 ${loaded ? 'opacity-100' : 'opacity-0'}`}
          onLoad={() => setLoaded(true)}
          onError={() => setError(true)}
          loading="lazy"
        />
      ) : (
        <div className="flex items-center justify-center w-full h-full text-text-tertiary text-xs text-center p-2">
          {alt}
        </div>
      )}
      {!loaded && !error && (
        <div className="absolute inset-0 bg-bg-tertiary animate-pulse" />
      )}
    </div>
  )
}
