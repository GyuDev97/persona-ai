import 'dart:math' as math;

import 'package:flutter/material.dart';

class CoreOrb extends StatelessWidget {
  const CoreOrb({
    required this.size,
    required this.glowOpacity,
    required this.animationValue,
    required this.isListening,
    required this.isBusy,
    required this.isSpeaking,
    super.key,
  });

  final double size;
  final double glowOpacity;
  final double animationValue;
  final bool isListening;
  final bool isBusy;
  final bool isSpeaking;

  @override
  Widget build(BuildContext context) {
    final accent = isListening
        ? const Color(0xFF6EFFF1)
        : isBusy
            ? const Color(0xFF3EE3D4)
            : const Color(0xFF2FD4C4);
    final speakingPulse = isSpeaking
        ? 1 + (math.sin(animationValue * math.pi * 6) * 0.09)
        : 1 + (math.sin(animationValue * math.pi * 2) * 0.02);
    final innerScale = isListening ? 1.03 : 1.0;

    return SizedBox(
      width: size,
      height: size,
      child: Stack(
        alignment: Alignment.center,
        children: [
          CustomPaint(
            size: Size.square(size),
            painter: _ParticleRingPainter(
              accent: accent,
              animationValue: animationValue,
              speakingPulse: speakingPulse,
              intensity: isListening ? 1.0 : (isBusy ? 0.8 : 0.65),
            ),
          ),
          Container(
            width: size,
            height: size,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              boxShadow: [
                BoxShadow(
                  color: accent.withOpacity(0.18 * glowOpacity),
                  blurRadius: 46,
                  spreadRadius: 18,
                ),
              ],
            ),
          ),
          Container(
            width: size * 0.96 * speakingPulse,
            height: size * 0.96 * speakingPulse,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              border: Border.all(color: accent.withOpacity(0.32), width: 3),
              gradient: RadialGradient(
                colors: [
                  accent.withOpacity(0.12),
                  const Color(0x14000000),
                ],
              ),
            ),
          ),
          Container(
            width: size * 0.78 * innerScale,
            height: size * 0.78 * innerScale,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              border: Border.all(color: accent.withOpacity(0.22), width: 2),
            ),
          ),
          Container(
            width: size * 0.54,
            height: size * 0.54,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              border: Border.all(color: accent.withOpacity(0.18), width: 1.5),
            ),
          ),
          Container(
            width: size * 0.2 * speakingPulse,
            height: size * 0.2 * speakingPulse,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: accent.withOpacity(0.22),
              border: Border.all(color: accent.withOpacity(0.62), width: 1.4),
              boxShadow: [
                BoxShadow(
                  color: accent.withOpacity(0.24),
                  blurRadius: 20,
                  spreadRadius: 4,
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _ParticleRingPainter extends CustomPainter {
  const _ParticleRingPainter({
    required this.accent,
    required this.animationValue,
    required this.speakingPulse,
    required this.intensity,
  });

  final Color accent;
  final double animationValue;
  final double speakingPulse;
  final double intensity;

  @override
  void paint(Canvas canvas, Size size) {
    final center = size.center(Offset.zero);
    final ringRadius = size.width * 0.34;
    final particlePaint = Paint()
      ..style = PaintingStyle.fill
      ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 6);

    for (var i = 0; i < 130; i++) {
      final baseAngle = (i / 130) * math.pi * 2;
      final orbit = animationValue * math.pi * 2 * (0.6 + (i % 7) * 0.045);
      final angle = baseAngle + orbit;
      final wobble = math.sin(animationValue * math.pi * 8 + i) * (size.width * 0.015);
      final radius = ringRadius + wobble;
      final depth = 0.78 + ((i % 11) / 40);
      final pulse = 0.75 + ((math.sin(animationValue * math.pi * 6 + i * 0.5) + 1) * 0.18);
      final dotRadius = (i % 5 == 0 ? 2.4 : 1.6) * speakingPulse * pulse;
      final position = Offset(
        center.dx + math.cos(angle) * radius * depth,
        center.dy + math.sin(angle) * radius * depth,
      );

      particlePaint.color = accent.withOpacity((0.18 + ((i % 9) / 18)) * intensity);
      canvas.drawCircle(position, dotRadius * 2.1, particlePaint);

      particlePaint
        ..maskFilter = null
        ..color = accent.withOpacity((0.48 + ((i % 7) / 18)) * intensity);
      canvas.drawCircle(position, dotRadius, particlePaint);
      particlePaint.maskFilter = const MaskFilter.blur(BlurStyle.normal, 6);
    }
  }

  @override
  bool shouldRepaint(covariant _ParticleRingPainter oldDelegate) {
    return oldDelegate.animationValue != animationValue ||
        oldDelegate.speakingPulse != speakingPulse ||
        oldDelegate.intensity != intensity ||
        oldDelegate.accent != accent;
  }
}
