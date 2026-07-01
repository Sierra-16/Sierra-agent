<template>
  <div class="sierra-ornament-frame" :class="[variant, { active, compact }]" aria-hidden="true">
    <span class="sierra-ornament-vine top"></span>
    <span class="sierra-ornament-vine bottom"></span>
    <span class="sierra-ornament-corner top-left"></span>
    <span class="sierra-ornament-corner top-right"></span>
    <span class="sierra-ornament-corner bottom-left"></span>
    <span class="sierra-ornament-corner bottom-right"></span>
    <span class="sierra-ornament-sparkles left"></span>
    <span class="sierra-ornament-sparkles right"></span>
  </div>
</template>

<script setup lang="ts">
withDefaults(
  defineProps<{
    active?: boolean;
    compact?: boolean;
    variant?: "button" | "process";
  }>(),
  {
    active: false,
    compact: false,
    variant: "process"
  }
);
</script>

<style scoped>
.sierra-ornament-frame {
  position: absolute;
  inset: 0;
  z-index: 0;
  overflow: hidden;
  border-radius: inherit;
  pointer-events: none;
}

.sierra-ornament-vine,
.sierra-ornament-corner,
.sierra-ornament-sparkles {
  position: absolute;
  display: block;
  background-repeat: no-repeat;
  pointer-events: none;
}

.sierra-ornament-vine {
  left: 134px;
  right: 18px;
  height: 42px;
  background-image: url("/brand/sierra-ui-vine-divider.png?v=ui-2");
  background-position: center;
  background-size: 100% auto;
  filter: drop-shadow(0 3px 8px rgba(0, 0, 0, 0.22));
  opacity: 0.62;
}

.sierra-ornament-vine.top {
  top: -8px;
  animation: sierra-vine-breathe 5.2s ease-in-out infinite alternate;
}

.sierra-ornament-vine.bottom {
  right: 150px;
  bottom: -10px;
  left: 18px;
  opacity: 0.36;
  transform: rotate(180deg);
}

.sierra-ornament-corner {
  width: 52px;
  height: 58px;
  background-image: url("/brand/sierra-ui-corner.png?v=ui-2");
  background-position: center;
  background-size: contain;
  opacity: 0.66;
  filter: drop-shadow(0 3px 8px rgba(0, 0, 0, 0.28));
}

.sierra-ornament-corner.top-left {
  top: 8px;
  left: 8px;
}

.sierra-ornament-corner.top-right {
  top: 8px;
  right: 8px;
  transform: scaleX(-1);
}

.sierra-ornament-corner.bottom-left {
  bottom: 8px;
  left: 8px;
  transform: scaleY(-1);
}

.sierra-ornament-corner.bottom-right {
  right: 8px;
  bottom: 8px;
  transform: scale(-1);
}

.sierra-ornament-sparkles {
  width: 210px;
  height: 52px;
  background-image: url("/brand/sierra-ui-sparkles.png?v=ui-2");
  background-position: center;
  background-size: contain;
  mix-blend-mode: screen;
  opacity: 0.18;
}

.sierra-ornament-sparkles.left {
  bottom: 8px;
  left: 108px;
  animation: sierra-sparkle-float 6.5s ease-in-out infinite alternate;
}

.sierra-ornament-sparkles.right {
  right: 110px;
  bottom: 9px;
  opacity: 0.16;
  animation: sierra-sparkle-float 7.4s ease-in-out infinite alternate-reverse;
}

.sierra-ornament-frame.active .sierra-ornament-vine.top {
  opacity: 0.76;
}

.sierra-ornament-frame.button {
  inset: 1px;
}

.sierra-ornament-frame.button .sierra-ornament-vine,
.sierra-ornament-frame.button .sierra-ornament-corner.bottom-left,
.sierra-ornament-frame.button .sierra-ornament-corner.bottom-right,
.sierra-ornament-frame.button .sierra-ornament-sparkles.left {
  display: none;
}

.sierra-ornament-frame.button .sierra-ornament-corner {
  top: -5px;
  width: 32px;
  height: 36px;
  opacity: 0.48;
}

.sierra-ornament-frame.button .sierra-ornament-corner.top-left {
  left: -4px;
}

.sierra-ornament-frame.button .sierra-ornament-corner.top-right {
  right: -4px;
}

.sierra-ornament-frame.button .sierra-ornament-sparkles.right {
  right: 10px;
  bottom: 0;
  width: 84px;
  height: 28px;
  opacity: 0.12;
}

.sierra-ornament-frame.button.compact .sierra-ornament-corner {
  width: 26px;
  height: 30px;
}

@keyframes sierra-vine-breathe {
  to {
    filter:
      drop-shadow(0 3px 8px rgba(0, 0, 0, 0.22))
      drop-shadow(0 0 10px rgba(246, 198, 91, 0.12));
    transform: translateY(1px);
  }
}

@keyframes sierra-sparkle-float {
  to {
    opacity: 0.28;
    transform: translate3d(8px, -2px, 0);
  }
}

@media (max-width: 780px) {
  .sierra-ornament-vine {
    left: 82px;
    right: 12px;
  }

  .sierra-ornament-vine.bottom,
  .sierra-ornament-sparkles.left {
    display: none;
  }

  .sierra-ornament-sparkles.right {
    right: 22px;
    width: 150px;
  }
}

@media (max-width: 560px) {
  .sierra-ornament-corner,
  .sierra-ornament-vine {
    opacity: 0.28;
  }
}
</style>
