import 'package:flutter/material.dart';

import '../api.dart';

/// Live provider status from the server: which AIs have keys and which see images.
class ProvidersScreen extends StatefulWidget {
  const ProvidersScreen({super.key, required this.api});
  final AutoMotoApi api;

  @override
  State<ProvidersScreen> createState() => _ProvidersScreenState();
}

class _ProvidersScreenState extends State<ProvidersScreen> {
  late Future<List<dynamic>> _future = widget.api.providers();

  @override
  Widget build(BuildContext context) {
    return RefreshIndicator(
      onRefresh: () async => setState(() => _future = widget.api.providers()),
      child: FutureBuilder<List<dynamic>>(
        future: _future,
        builder: (context, snap) {
          if (snap.connectionState != ConnectionState.done) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snap.hasError) {
            return ListView(padding: const EdgeInsets.all(24), children: [
              Text("Can't reach your AutoMoto server.\n\n${snap.error}\n\nCheck the server URL and token on the Keys tab."),
            ]);
          }
          final list = snap.data!;
          return ListView(
            padding: const EdgeInsets.all(12),
            children: [
              const ListTile(
                title: Text('AI providers', style: TextStyle(fontWeight: FontWeight.bold)),
                subtitle: Text('Auto mode tries the best ready AI, then fails over. 👁 = understands images.'),
              ),
              for (final p in list)
                Card(
                  child: ListTile(
                    leading: Icon(
                      p['configured'] == true ? Icons.check_circle : Icons.radio_button_unchecked,
                      color: p['configured'] == true ? Colors.greenAccent : null,
                    ),
                    title: Text('${p['label']}${p['supports_vision'] == true ? '  👁' : ''}'),
                    subtitle: Text(
                      '${p['configured'] == true ? 'Ready' : 'Add ${(p['env_keys'] as List).first}'}'
                      ' · ${p['free_tier'] == true ? 'free tier' : 'paid'}\n'
                      'text: ${p['text_model']}'
                      '${p['vision_model'] != null ? '\nvision: ${p['vision_model']}' : ''}',
                    ),
                    isThreeLine: true,
                  ),
                ),
            ],
          );
        },
      ),
    );
  }
}
