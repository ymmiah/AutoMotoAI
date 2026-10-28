// AutoMoto AI v4 "Cousin" - mobile client.
// Built by Yasin Mohammed Miah (ymmiah), Student of BCU, BSc Computing Top-Up (Hons).
//
// Phones don't get desktop automation. This app does chat, provider status,
// BYOK key storage (Keychain / Android Keystore) and image/camera attach for
// vision questions. The AutoMoto Python server does the AI routing.
import 'package:flutter/material.dart';

import 'api.dart';
import 'screens/chat_screen.dart';
import 'screens/providers_screen.dart';
import 'screens/settings_screen.dart';

void main() => runApp(const AutoMotoApp());

class AutoMotoApp extends StatelessWidget {
  const AutoMotoApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'AutoMoto AI',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFF38F2A5),
          brightness: Brightness.dark,
        ),
        useMaterial3: true,
      ),
      home: const HomeShell(),
    );
  }
}

class HomeShell extends StatefulWidget {
  const HomeShell({super.key});

  @override
  State<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends State<HomeShell> {
  final api = AutoMotoApi();
  int index = 0;

  @override
  Widget build(BuildContext context) {
    final pages = [
      ChatScreen(api: api),
      ProvidersScreen(api: api),
      SettingsScreen(api: api),
    ];
    return Scaffold(
      body: SafeArea(child: pages[index]),
      bottomNavigationBar: NavigationBar(
        selectedIndex: index,
        onDestinationSelected: (i) => setState(() => index = i),
        destinations: const [
          NavigationDestination(icon: Icon(Icons.chat_bubble_outline), label: 'Chat'),
          NavigationDestination(icon: Icon(Icons.hub_outlined), label: 'AIs'),
          NavigationDestination(icon: Icon(Icons.key_outlined), label: 'Keys'),
        ],
      ),
    );
  }
}
