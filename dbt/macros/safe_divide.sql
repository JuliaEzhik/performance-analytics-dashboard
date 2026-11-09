{#- Division that returns NULL instead of failing when the denominator is 0 or NULL. -#}
{% macro safe_divide(numerator, denominator) -%}
    (({{ numerator }}) / nullif(({{ denominator }}), 0))
{%- endmacro %}
