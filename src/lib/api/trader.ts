// src/lib/api/trader.ts
import { supabase } from '@/integrations/supabase/client';

export async function getCatalog(assetClass?: string) {
  let q = supabase
    .from('signal_products')
    .select('*')
    .eq('is_published', true)
    .order('forward_win_rate', { ascending: false });

  if (assetClass && assetClass !== 'all') {
    q = q.eq('asset_class', assetClass);
  }

  const { data, error } = await q;
  if (error) throw error;
  return data ?? [];
}

export async function getProduct(productId: string) {
  const { data, error } = await supabase
    .from('signal_products')
    .select('*')
    .eq('id', productId)
    .single();
  if (error) throw error;
  return data;
}

export async function getMySubscriptions() {
  const { data, error } = await supabase
    .from('product_subscriptions')
    .select('*, signal_products(*)')
    .is('ended_at', null);
  if (error) throw error;
  return data ?? [];
}

export async function isSubscribed(productId: string) {
  const { data, error } = await supabase
    .from('product_subscriptions')
    .select('id')
    .eq('product_id', productId)
    .is('ended_at', null)
    .maybeSingle();
  if (error) throw error;
  return !!data;
}

export async function subscribeToProduct(productId: string) {
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) throw new Error('Not authenticated');

  const { data, error } = await supabase
    .from('product_subscriptions')
    .insert({
      user_id: user.id,
      product_id: productId,
      paid: false,
    })
    .select()
    .single();
  if (error) throw error;
  return data;
}

export async function unsubscribeFromProduct(productId: string) {
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) throw new Error('Not authenticated');

  const { error } = await supabase
    .from('product_subscriptions')
    .update({ ended_at: new Date().toISOString() })
    .eq('user_id', user.id)
    .eq('product_id', productId)
    .is('ended_at', null);
  if (error) throw error;
}

export async function getRecentSignals(limit = 50) {
  const { data, error } = await supabase
    .from('signals')
    .select('*, signal_products(name, asset_class, slug)')
    .order('fired_at', { ascending: false })
    .limit(limit);
  if (error) throw error;
  return data ?? [];
}

export async function getSignal(signalId: string) {
  const { data, error } = await supabase
    .from('signals')
    .select('*, signal_products(name, asset_class, slug, description)')
    .eq('id', signalId)
    .single();
  if (error) throw error;
  return data;
}

export async function getOpenSignals() {
  const { data, error } = await supabase
    .from('signals')
    .select('*, signal_products(name, asset_class)')
    .eq('status', 'open')
    .order('fired_at', { ascending: false });
  if (error) throw error;
  return data ?? [];
}

export async function getTakenSignals() {
  const { data, error } = await supabase
    .from('taken_signals')
    .select('*, signals(*, signal_products(name, asset_class))')
    .order('taken_at', { ascending: false });
  if (error) throw error;
  return data ?? [];
}

export async function markSignalTaken(
  signalId: string,
  fillPrice: number,
  source: 'manual' | 'broker' | 'agent'
) {
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) throw new Error('Not authenticated');

  const { data, error } = await supabase
    .from('taken_signals')
    .insert({
      user_id: user.id,
      signal_id: signalId,
      fill_price: fillPrice,
      source,
    })
    .select()
    .single();
  if (error) throw error;
  return data;
}

export async function getUserPreferences() {
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) return {};

  const { data, error } = await supabase
    .from('user_preferences')
    .select('prefs')
    .eq('user_id', user.id)
    .maybeSingle();
  if (error) throw error;
  return data?.prefs ?? {};
}

export async function updateUserPreferences(prefs: any) {
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) throw new Error('Not authenticated');

  const { error } = await supabase
    .from('user_preferences')
    .upsert({
      user_id: user.id,
      prefs,
      updated_at: new Date().toISOString(),
    });
  if (error) throw error;
}

export async function getPlanState() {
  const { data, error } = await supabase
    .from('plan_state')
    .select('*')
    .maybeSingle();
  if (error) throw error;
  return data;
}

export function subscribeToSignals(onNewSignal: (signal: any) => void) {
  const channel = supabase
    .channel('signals-realtime')
    .on('postgres_changes',
      { event: 'INSERT', schema: 'public', table: 'signals' },
      (payload) => onNewSignal(payload.new))
    .subscribe();
  return () => supabase.removeChannel(channel);
}

export function subscribeToSignalUpdates(onUpdate: (signal: any) => void) {
  const channel = supabase
    .channel('signals-updates')
    .on('postgres_changes',
      { event: 'UPDATE', schema: 'public', table: 'signals' },
      (payload) => onUpdate(payload.new))
    .subscribe();
  return () => supabase.removeChannel(channel);
}
