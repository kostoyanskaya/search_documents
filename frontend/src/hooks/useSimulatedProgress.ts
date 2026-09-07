import { useEffect, useRef, useState } from 'react'

/**
 * Бэкенд не отдаёт реальный прогресс индексации (0-100%), поэтому здесь
 * симулируется правдоподобная кривая приближения к ~92%, пока active=true,
 * и мгновенный переход к 100% по завершении.
 */
export function useSimulatedProgress(active: boolean): number {
  const [percent, setPercent] = useState(0)
  const startRef = useRef<number | null>(null)

  useEffect(() => {
    if (!active) {
      const t = setTimeout(() => setPercent(0), 500)
      return () => clearTimeout(t)
    }

    if (startRef.current === null) {
      startRef.current = Date.now()
    }

    const tick = () => {
      const elapsed = (Date.now() - (startRef.current ?? Date.now())) / 1000
      setPercent(92 * (1 - Math.exp(-elapsed / 4)))
    }

    const id = setInterval(tick, 120)
    tick()

    return () => clearInterval(id)
  }, [active])

  useEffect(() => {
    if (!active) {
      startRef.current = null
    }
  }, [active])

  return active ? percent : 100
}
