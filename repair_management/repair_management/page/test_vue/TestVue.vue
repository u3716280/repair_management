<script setup>
import { ref } from 'vue'

const message = ref('Hello, World')
</script>

<template>
  <h1>{{ message }}</h1>
  <h2>You CALL FROM Vue File </h2>
</template>
