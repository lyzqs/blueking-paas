<template>
  <div class="config-input-container">
    <bk-input
      :value="$attrs.value"
      :type="type === 'input' ? undefined : type"
      v-bind="$attrs"
      show-word-limit
      @input="$emit('input', $event)"
      @focus="$emit('focus', $event)"
      @blur="$emit('blur', $event)"
    ></bk-input>
  </div>
</template>

<script>
export default {
  name: 'ConfigInputContainer',
  props: {
    type: {
      default: '',
    },
  },
};
</script>

<style lang="scss" scoped></style>
