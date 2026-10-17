import 'package:flutter/material.dart';

class CoreActionButton extends StatelessWidget {
  const CoreActionButton({
    required this.icon,
    required this.label,
    required this.onTap,
    this.accent = false,
    super.key,
  });

  final IconData icon;
  final String label;
  final VoidCallback onTap;
  final bool accent;

  @override
  Widget build(BuildContext context) {
    return FilledButton.icon(
      onPressed: onTap,
      style: FilledButton.styleFrom(
        backgroundColor: accent ? const Color(0xFF1CCAB8) : const Color(0x2217FFF0),
        foregroundColor: accent ? const Color(0xFF03211E) : const Color(0xFFD9FFFA),
        padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 14),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
        side: accent ? BorderSide.none : const BorderSide(color: Color(0x3348CFC2)),
      ),
      icon: Icon(icon),
      label: Text(label),
    );
  }
}
