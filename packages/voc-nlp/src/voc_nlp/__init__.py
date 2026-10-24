"""voc-nlp: lógica pura de inferencia y monitoreo de BBVA VoC Analyzer.

Porta de ``voc_analytics`` (EPIC-5) los criterios que decidió esa épica, sin
cambiarlos. Los módulos con dependencias pesadas viven en *extras*:
``sentiment_model`` y ``explain`` (``[sentiment]``), ``aspects``
(``[gemini]``) y ``topics`` (``[topics]``).
"""
