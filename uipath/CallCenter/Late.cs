using System;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Threading;

namespace CallCenter
{
    /// <summary>
    /// Excel COM 개체를 참조 추가 없이 호출하기 위한 늦은 바인딩 도우미.
    /// (dynamic / Interop 어셈블리 의존성을 피하려는 목적)
    /// 엑셀이 일시적으로 "바쁨" 상태일 때(RPC_E_SERVERCALL_RETRYLATER 등)는 자동으로 재시도한다.
    /// </summary>
    public static class Late
    {
        private const int MaxRetries = 40;      // 최대 40회
        private const int RetryDelayMs = 250;   // 250ms 간격 → 최대 약 10초

        public static object Get(object target, string name, params object[] args)
        {
            return Invoke(target, name, BindingFlags.GetProperty, args);
        }

        public static void Set(object target, string name, params object[] args)
        {
            Invoke(target, name, BindingFlags.SetProperty, args);
        }

        public static object Call(object target, string name, params object[] args)
        {
            return Invoke(target, name, BindingFlags.InvokeMethod, args);
        }

        private static object Invoke(object target, string name, BindingFlags flags, object[] args)
        {
            int attempt = 0;
            while (true)
            {
                try
                {
                    return target.GetType().InvokeMember(name, flags, null, target, args);
                }
                catch (TargetInvocationException ex)
                {
                    COMException ce = ex.InnerException as COMException;
                    if (ce != null && IsBusy(ce.HResult) && attempt < MaxRetries)
                    {
                        attempt++;
                        Thread.Sleep(RetryDelayMs);
                        continue;
                    }
                    throw;
                }
                catch (COMException ce2)
                {
                    if (IsBusy(ce2.HResult) && attempt < MaxRetries)
                    {
                        attempt++;
                        Thread.Sleep(RetryDelayMs);
                        continue;
                    }
                    throw;
                }
            }
        }

        // 0x8001010A RPC_E_SERVERCALL_RETRYLATER, 0x80010001 RPC_E_CALL_REJECTED, 0x800AC472 VBA_E_IGNORE(엑셀 바쁨)
        private static bool IsBusy(int hresult)
        {
            uint h = unchecked((uint)hresult);
            return h == 0x8001010A || h == 0x80010001 || h == 0x800AC472;
        }

        public static void Release(object o)
        {
            if (o != null && Marshal.IsComObject(o))
            {
                try { Marshal.ReleaseComObject(o); } catch (Exception) { }
            }
        }
    }
}
