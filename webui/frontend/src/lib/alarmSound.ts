/** 告警提示音（T93）：Web Audio 短蜂鸣；AudioContext 不可用时静默（值守场景不弹错）. */
let ctx: AudioContext | null = null

export function alarmBeep(): void {
  try {
    if (ctx === null) {
      const AC = window.AudioContext
      if (!AC) return
      ctx = new AC()
    }
    if (ctx.state === 'suspended') void ctx.resume()
    const osc = ctx.createOscillator()
    const gain = ctx.createGain()
    osc.connect(gain)
    gain.connect(ctx.destination)
    osc.frequency.value = 880
    gain.gain.value = 0.06
    osc.start()
    osc.stop(ctx.currentTime + 0.15)
  } catch {
    // 提示音失败不影响值守
  }
}
