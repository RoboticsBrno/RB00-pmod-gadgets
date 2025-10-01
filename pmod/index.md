# PMOD

Všechny naše PMOD moduly:

{% set imgNameList = generateTemplateImgNameList() %}
{% set printEnd = false %}

<div markdown class="gadgets-display">
{% for batch in imgNameList|batch(3) %}
<div markdown class="container">
{% for imgPath, name, path in batch %}
<div markdown class="col-1-3 gadget">
<a href="{{ path }}" class="gadget-link">
![PMOD Image]({{ imgPath }})
[{{ name }}]({{ path }})
</a>
</div>
{% endfor %}
</div>
{% endfor %}
</div>
